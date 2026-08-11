from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tennis_quant.domain import Candidate, MarketSide
from tennis_quant.features import (
    combined_recent_strength,
    fatigue_readiness,
    h2h_rate,
    pair_probability,
    profile_strength,
    ranking_probability,
    serve_strength,
)
from tennis_quant.market import consensus_market
from tennis_quant.prediction import confidence_score, disagreement_pp, weighted_probability
from tennis_quant.ratings import RatingStore, margin_k
from tennis_quant.selection import rank_candidates
from tennis_quant.storage import write_json, write_snapshot


def _extract_home_away(raw: dict[str, Any]) -> tuple[dict, dict]:
    home_away = raw.get("Home/Away", {}) if isinstance(raw, dict) else {}
    home = home_away.get("Home", {}) or {}
    away = home_away.get("Away", {}) or {}
    return home, away


def _is_prematch(match) -> bool:
    status = str(match.status or "").strip().lower()
    live = str(match.raw.get("event_live", "0")).strip().lower()
    winner = str(match.winner or "").strip()
    terminal = ("finished", "cancel", "retired", "walkover", "abandoned", "postponed")
    if winner or live in {"1", "true", "yes"}:
        return False
    return not any(token in status for token in terminal)


def _winner_loser(match) -> tuple[str, str] | None:
    winner = str(match.winner or match.raw.get("event_winner") or "").strip().lower()
    if winner == "first player":
        return match.player_a.key, match.player_b.key
    if winner == "second player":
        return match.player_b.key, match.player_a.key
    return None


def _bootstrap_ratings(provider, ratings: RatingStore, target_date: date, days: int = 365) -> dict[str, Any]:
    if ratings.bootstrap_done():
        return {"status": "READY", **ratings.data.get("bootstrap", {})}
    start = target_date - timedelta(days=days)
    end = target_date - timedelta(days=1)
    updated = 0
    try:
        history = provider.fixtures_range(start, end)
        history.sort(key=lambda m: (m.date, m.time, m.match_id))
        for match in history:
            result = _winner_loser(match)
            if not result:
                continue
            winner, loser = result
            if ratings.record_match(
                match.match_id,
                winner,
                loser,
                match.surface,
                k=margin_k(match.raw.get("event_final_result")),
            ):
                updated += 1
        ratings.mark_bootstrap(start.isoformat(), end.isoformat(), updated)
        ratings.save()
        return {"status": "BUILT", "start": start.isoformat(), "end": end.isoformat(), "matches": updated}
    except Exception as exc:
        # Analysis still runs using ranking/market/form if historical bootstrap is temporarily unavailable.
        return {"status": "DEGRADED", "error": str(exc)[:300], "matches": len(ratings.data.get("processed_matches", []))}


def _load_enrichment_cache(root: Path, day: str) -> tuple[Path, dict[str, Any]]:
    path = root / "data" / "cache" / "enrichment" / f"{day}.json"
    if not path.exists():
        return path, {"profiles": {}, "histories": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("profiles", {})
        payload.setdefault("histories", {})
        return path, payload
    except (ValueError, OSError):
        return path, {"profiles": {}, "histories": {}}


def _compact_history(matches: list[Any], limit: int = 16) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for match in matches[:limit]:
        raw = match.raw if hasattr(match, "raw") else match
        if not isinstance(raw, dict):
            continue
        output.append({
            "event_key": raw.get("event_key"),
            "event_date": raw.get("event_date"),
            "event_final_result": raw.get("event_final_result"),
            "event_winner": raw.get("event_winner"),
            "first_player_key": raw.get("first_player_key"),
            "second_player_key": raw.get("second_player_key"),
            "statistics": raw.get("statistics", []),
        })
    return output


def _get_profile(provider, cache: dict[str, Any], player_key: str) -> dict[str, Any]:
    profiles = cache["profiles"]
    if player_key not in profiles:
        try:
            profiles[player_key] = provider.player_profile(player_key)
        except Exception:
            profiles[player_key] = {}
    return profiles[player_key]


def _get_history(provider, cache: dict[str, Any], player_key: str, target_date: date) -> list[dict[str, Any]]:
    histories = cache["histories"]
    if player_key not in histories:
        try:
            matches = provider.player_history(player_key, target_date - timedelta(days=120), target_date - timedelta(days=1))
            matches.sort(key=lambda m: (m.date, m.time), reverse=True)
            histories[player_key] = _compact_history(matches)
        except Exception:
            histories[player_key] = []
    return histories[player_key]


def _market_in_scope(market: dict[str, Any], cfg: dict) -> bool:
    s = cfg["selection"]
    for odd in (market.get("home_best"), market.get("away_best")):
        if odd is not None and s["min_odd"] <= float(odd) <= s["max_odd"]:
            return True
    return False


def _quality_score(
    bookmakers: int,
    recent_seen: int,
    ranking_ok: bool,
    profile_samples: int,
    serve_samples: int,
    bootstrap_ok: bool,
    has_surface: bool,
) -> float:
    score = 0.20
    score += min(bookmakers, 10) * 0.025
    score += min(recent_seen, 16) * 0.0125
    score += 0.09 if ranking_ok else 0.0
    score += min(profile_samples, 20) * 0.006
    score += min(serve_samples, 10) * 0.010
    score += 0.09 if bootstrap_ok else 0.0
    score += 0.04 if has_surface else 0.0
    return min(1.0, score)


def analyze_day(provider, target_date: date, cfg: dict, root: Path, h2h_budget: int = 40) -> dict[str, Any]:
    day = target_date.isoformat()
    fixtures = provider.fixtures(target_date)
    prematch = [m for m in fixtures if str(m.event_type).lower() == "atp singles" and _is_prematch(m)]
    odds_by_match = provider.odds(target_date)
    ratings = RatingStore(root / "data" / "state" / "ratings.json")
    bootstrap = _bootstrap_ratings(provider, ratings, target_date, int(cfg.get("bootstrap_days", 365)))

    try:
        standings = provider.standings("ATP")
    except Exception:
        standings = {}

    cache_path, enrichment_cache = _load_enrichment_cache(root, day)
    candidates: list[Candidate] = []
    h2h_calls = 0
    odds_matches = 0
    deep_matches = 0

    for match in prematch:
        raw_odds = odds_by_match.get(match.match_id, {})
        home, away = _extract_home_away(raw_odds)
        market = consensus_market(home, away)
        if not market["bookmakers"]:
            continue
        odds_matches += 1

        # Stage 1: every ATP Singles fixture is screened by market. Expensive enrichment only runs
        # when at least one side can actually become a 1.50-2.00 selection.
        if not _market_in_scope(market, cfg):
            continue
        deep_matches += 1

        elo_a, surf_a = ratings.probability(match.player_a.key, match.player_b.key, match.surface)
        rank_a = standings.get(match.player_a.key)
        rank_b = standings.get(match.player_b.key)
        rank_prob_a = ranking_probability(rank_a, rank_b)

        context: dict[str, Any] = {}
        if h2h_calls < h2h_budget:
            try:
                context = provider.h2h(match.player_a.key, match.player_b.key)
                h2h_calls += 1
            except Exception:
                context = {}

        recent_a_rows = context.get("firstPlayerResults", []) or []
        recent_b_rows = context.get("secondPlayerResults", []) or []
        recent_a, a_seen = combined_recent_strength(recent_a_rows, match.player_a.key)
        recent_b, b_seen = combined_recent_strength(recent_b_rows, match.player_b.key)
        form_prob_a = pair_probability(recent_a, recent_b, scale=0.85)

        h2h_prob_a, h_seen = h2h_rate(context.get("H2H", []) or [], match.player_a.key)
        if h_seen < 2:
            h2h_prob_a = None

        ready_a, fatigue_a = fatigue_readiness(recent_a_rows, target_date)
        ready_b, fatigue_b = fatigue_readiness(recent_b_rows, target_date)
        fatigue_prob_a = pair_probability(ready_a, ready_b, scale=0.45)

        profile_a = _get_profile(provider, enrichment_cache, match.player_a.key)
        profile_b = _get_profile(provider, enrichment_cache, match.player_b.key)
        p_strength_a, p_seen_a = profile_strength(profile_a, target_date.year, match.surface)
        p_strength_b, p_seen_b = profile_strength(profile_b, target_date.year, match.surface)
        profile_prob_a = pair_probability(p_strength_a, p_strength_b, scale=0.75) if (p_seen_a or p_seen_b) else None

        hist_a = _get_history(provider, enrichment_cache, match.player_a.key, target_date)
        hist_b = _get_history(provider, enrichment_cache, match.player_b.key, target_date)
        serve_a, serve_seen_a = serve_strength(hist_a, match.player_a.key)
        serve_b, serve_seen_b = serve_strength(hist_b, match.player_b.key)
        serve_prob_a = (
            pair_probability(serve_a, serve_b, scale=1.10)
            if serve_a is not None and serve_b is not None
            else None
        )

        signals_a: dict[str, float | None] = {
            "market": market["home_fair"],
            "elo": elo_a,
            "surface_elo": surf_a if match.surface else None,
            "ranking": rank_prob_a,
            "recent_form": form_prob_a,
            "season_profile": profile_prob_a,
            "fatigue": fatigue_prob_a,
            "serve": serve_prob_a,
            "h2h": h2h_prob_a,
        }
        signals_b = {k: (None if v is None else 1.0 - float(v)) for k, v in signals_a.items()}

        ranking_ok = rank_prob_a is not None
        profile_samples = p_seen_a + p_seen_b
        serve_samples = serve_seen_a + serve_seen_b
        data_quality = _quality_score(
            int(market["bookmakers"]),
            a_seen + b_seen,
            ranking_ok,
            profile_samples,
            serve_samples,
            bootstrap.get("status") in {"READY", "BUILT"},
            bool(match.surface),
        )

        sides = [
            (
                match.player_a, match.player_b,
                market["home_best"], market["home_median"], market["home_fair"],
                market["away_best"], market["away_median"], market["away_fair"],
                signals_a,
            ),
            (
                match.player_b, match.player_a,
                market["away_best"], market["away_median"], market["away_fair"],
                market["home_best"], market["home_median"], market["home_fair"],
                signals_b,
            ),
        ]

        for selected, opponent, best, med, fair, obest, omed, ofair, signals in sides:
            if best is None or fair is None:
                continue
            clean_signals = {k: v for k, v in signals.items() if v is not None}
            final = weighted_probability(clean_signals, cfg["ensemble_weights"])
            edge = (final - float(fair)) * 100.0
            disagree = disagreement_pp(clean_signals)
            confidence = confidence_score(final, edge, disagree, data_quality, cfg["confidence_weights"])
            candidate = Candidate(
                match=match,
                selected_player=selected,
                opponent=opponent,
                selected_market=MarketSide(selected.key, best, med, fair, int(market["bookmakers"])),
                opponent_market=MarketSide(opponent.key, obest, omed, ofair, int(market["bookmakers"])),
                signals=clean_signals,
                final_probability=final,
                market_probability=float(fair),
                edge_pp=edge,
                disagreement_pp=disagree,
                data_quality=data_quality,
                confidence=confidence,
                model_version=cfg["model_version"],
            )
            # Keep audit-only context outside the model signals. It is removed from immutable match.raw
            # by Candidate.to_dict(), so no oversized API payload leaks into the dashboard.
            candidate.match.raw.setdefault("analysis_context", {})[selected.key] = {
                "rank": (rank_a if selected.key == match.player_a.key else rank_b),
                "fatigue": (fatigue_a if selected.key == match.player_a.key else fatigue_b),
                "serve_sample": (serve_seen_a if selected.key == match.player_a.key else serve_seen_b),
            }
            candidates.append(candidate)

    write_json(cache_path, enrichment_cache)
    ranked = rank_candidates(candidates, cfg)
    payload = {
        "date": day,
        "model_version": cfg["model_version"],
        "generated_at_timezone": "America/Sao_Paulo",
        "fixtures_analyzed": len(fixtures),
        "prematch_atp_singles": len(prematch),
        "matches_with_odds": odds_matches,
        "deep_analyzed_matches": deep_matches,
        "candidate_sides": len(ranked),
        "api_requests": getattr(provider, "request_count", None),
        "bootstrap": bootstrap,
        "approved": [c.to_dict() for c in ranked if c.status == "APPROVED"],
        "shadow": [c.to_dict() for c in ranked if c.status == "SHADOW"],
        "rejected": [c.to_dict() for c in ranked if c.status == "REJECTED"],
    }
    write_json(root / "data" / "daily" / f"{day}.json", payload)
    write_json(root / "dashboard" / "data.json", payload)
    for candidate in ranked:
        if candidate.status in {"APPROVED", "SHADOW"}:
            write_snapshot(root / "data", day, candidate.to_dict())
    return payload
