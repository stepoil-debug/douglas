from __future__ import annotations

import json
from datetime import date, datetime, timedelta
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
    winner = str(match.winner or "").strip()
    terminal = ("finished", "started", "live", "cancel", "retired", "walkover", "abandoned", "postponed")
    if winner:
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
    source = str(getattr(provider, "history_source_id", "public-history"))
    source_reset = ratings.ensure_source(source)
    if ratings.bootstrap_done(source):
        return {"status": "READY", "source_reset": source_reset, **ratings.data.get("bootstrap", {})}
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
        ratings.mark_bootstrap(start.isoformat(), end.isoformat(), updated, source=source)
        ratings.save()
        return {
            "status": "BUILT",
            "source": source,
            "source_reset": source_reset,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "matches": updated,
        }
    except Exception as exc:
        return {
            "status": "DEGRADED",
            "source": source,
            "source_reset": source_reset,
            "error": str(exc)[:300],
            "matches": len(ratings.data.get("processed_matches", [])),
        }


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
    """Return whether at least one side is in the execution odd range.

    This is a diagnostic/selection-pool flag only. It must never gate the full
    pre-match analysis, because the model needs to study the whole ATP board first.
    """
    s = cfg["selection"]
    for odd in (market.get("home_best"), market.get("away_best")):
        if odd is not None and s["min_odd"] <= float(odd) <= s["max_odd"]:
            return True
    return False


def _recover_surface(provider, match: Any, target_date: date, lookback_years: int = 3) -> str | None:
    """Recover a missing live surface from the same tournament in recent seasons.

    Current-season static files may not contain a tournament until it has completed.
    Looking back a few editions is safer than silently dropping surface Elo/profile data.
    """
    current = str(getattr(match, "surface", "") or "").strip()
    if current:
        return current
    store = getattr(provider, "sackmann", None)
    resolver = getattr(store, "surface_for_tournament", None)
    if not callable(resolver):
        return None
    for offset in range(max(1, int(lookback_years))):
        year = target_date.year - offset
        try:
            inferred = str(resolver(match.tournament, year) or "").strip()
        except Exception:
            inferred = ""
        if inferred:
            match.surface = inferred
            return inferred
    return None


def _fresh_ranking(
    provider: Any,
    standings: dict[str, dict[str, Any]],
    player_key: str,
    target_date: date,
    max_age_days: int = 8,
) -> dict[str, Any] | None:
    """Use match-file ranking only while it is recent enough to represent the player now."""
    row = standings.get(player_key)
    if not row:
        return None
    store = getattr(provider, "sackmann", None)
    raw = (getattr(store, "latest_rank", {}) or {}).get(player_key) if store is not None else None
    raw_date = str((raw or {}).get("date") or "").strip()
    if not raw_date:
        return row
    try:
        ranked_on = datetime.strptime(raw_date, "%Y%m%d").date()
    except ValueError:
        return None
    age = (target_date - ranked_on).days
    if age < 0 or age > max(0, int(max_age_days)):
        return None
    return row


def _quality_score(
    bookmakers: int,
    recent_seen: int,
    ranking_ok: bool,
    profile_samples: int,
    serve_samples: int,
    bootstrap_ok: bool,
    has_surface: bool,
    identity_resolved: bool,
) -> float:
    score = 0.17
    score += min(bookmakers, 10) * 0.026
    score += min(recent_seen, 16) * 0.012
    score += 0.09 if ranking_ok else 0.0
    score += min(profile_samples, 20) * 0.006
    score += min(serve_samples, 10) * 0.010
    score += 0.09 if bootstrap_ok else 0.0
    score += 0.04 if has_surface else 0.0
    score += 0.06 if identity_resolved else 0.0
    return min(1.0, score)


def _bookmaker_odds(rows: dict[str, Any]) -> dict[str, float]:
    clean: dict[str, float] = {}
    for bookmaker, odd in (rows or {}).items():
        try:
            value = float(odd)
        except (TypeError, ValueError):
            continue
        if value > 1:
            clean[str(bookmaker)] = value
    return clean


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
    # Public-history H2H is local/static after download. A fixed cap must not make
    # later matches on a large ATP card receive a shallower analysis.
    effective_h2h_budget = max(int(h2h_budget or 0), len(prematch))
    odds_matches = 0
    deep_matches = 0
    target_odd_matches = 0
    no_market_matches = 0
    unresolved_players: set[str] = set()
    recovered_surfaces = 0
    stale_rankings_ignored = 0

    for match in prematch:
        raw_odds = odds_by_match.get(match.match_id, {})
        home, away = _extract_home_away(raw_odds)
        market = consensus_market(home, away)
        if not market["bookmakers"]:
            no_market_matches += 1
            continue

        odds_matches += 1
        deep_matches += 1
        if _market_in_scope(market, cfg):
            target_odd_matches += 1

        if not match.surface and _recover_surface(provider, match, target_date, int(cfg.get("surface_lookback_years", 3))):
            recovered_surfaces += 1

        resolved_a = not str(match.player_a.key).startswith("name-")
        resolved_b = not str(match.player_b.key).startswith("name-")
        if not resolved_a:
            unresolved_players.add(match.player_a.name)
        if not resolved_b:
            unresolved_players.add(match.player_b.name)

        elo_a, surf_a = ratings.probability(match.player_a.key, match.player_b.key, match.surface)
        raw_rank_a = standings.get(match.player_a.key)
        raw_rank_b = standings.get(match.player_b.key)
        rank_a = _fresh_ranking(provider, standings, match.player_a.key, target_date, int(cfg.get("ranking_max_age_days", 8)))
        rank_b = _fresh_ranking(provider, standings, match.player_b.key, target_date, int(cfg.get("ranking_max_age_days", 8)))
        if raw_rank_a and not rank_a:
            stale_rankings_ignored += 1
        if raw_rank_b and not rank_b:
            stale_rankings_ignored += 1
        rank_prob_a = ranking_probability(rank_a, rank_b)

        context: dict[str, Any] = {}
        if resolved_a and resolved_b and h2h_calls < effective_h2h_budget:
            try:
                context = provider.h2h(match.player_a.key, match.player_b.key)
                h2h_calls += 1
            except Exception:
                context = {}

        recent_a_rows = context.get("firstPlayerResults", []) or []
        recent_b_rows = context.get("secondPlayerResults", []) or []
        recent_a, a_seen = combined_recent_strength(recent_a_rows, match.player_a.key)
        recent_b, b_seen = combined_recent_strength(recent_b_rows, match.player_b.key)
        form_prob_a = pair_probability(recent_a, recent_b, scale=0.85) if (a_seen or b_seen) else None

        h2h_prob_a, h_seen = h2h_rate(context.get("H2H", []) or [], match.player_a.key)
        if h_seen < 2:
            h2h_prob_a = None

        ready_a, fatigue_a = fatigue_readiness(recent_a_rows, target_date)
        ready_b, fatigue_b = fatigue_readiness(recent_b_rows, target_date)
        fatigue_prob_a = pair_probability(ready_a, ready_b, scale=0.35) if (a_seen and b_seen) else None

        profile_a = _get_profile(provider, enrichment_cache, match.player_a.key) if resolved_a else {}
        profile_b = _get_profile(provider, enrichment_cache, match.player_b.key) if resolved_b else {}
        p_strength_a, p_seen_a = profile_strength(profile_a, target_date.year, match.surface)
        p_strength_b, p_seen_b = profile_strength(profile_b, target_date.year, match.surface)
        profile_prob_a = pair_probability(p_strength_a, p_strength_b, scale=0.75) if (p_seen_a or p_seen_b) else None

        hist_a = _get_history(provider, enrichment_cache, match.player_a.key, target_date) if resolved_a else []
        hist_b = _get_history(provider, enrichment_cache, match.player_b.key, target_date) if resolved_b else []
        serve_a, serve_seen_a = serve_strength(hist_a, match.player_a.key)
        serve_b, serve_seen_b = serve_strength(hist_b, match.player_b.key)
        serve_prob_a = pair_probability(serve_a, serve_b, scale=1.10) if serve_a is not None and serve_b is not None else None

        signals_a: dict[str, float | None] = {
            "market": market["home_fair"],
            "elo": elo_a if resolved_a and resolved_b else None,
            "surface_elo": surf_a if match.surface and resolved_a and resolved_b else None,
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
        identity_resolved = resolved_a and resolved_b
        data_quality = _quality_score(
            int(market["bookmakers"]),
            a_seen + b_seen,
            ranking_ok,
            profile_samples,
            serve_samples,
            bootstrap.get("status") in {"READY", "BUILT"},
            bool(match.surface),
            identity_resolved,
        )

        sides = [
            (
                match.player_a, match.player_b,
                market["home_best"], market["home_median"], market["home_fair"],
                market["away_best"], market["away_median"], market["away_fair"],
                signals_a, home, away,
            ),
            (
                match.player_b, match.player_a,
                market["away_best"], market["away_median"], market["away_fair"],
                market["home_best"], market["home_median"], market["home_fair"],
                signals_b, away, home,
            ),
        ]

        for selected, opponent, best, med, fair, obest, omed, ofair, signals, selected_books, opponent_books in sides:
            if best is None or fair is None:
                continue
            clean_signals = {k: float(v) for k, v in signals.items() if v is not None}
            final = weighted_probability(clean_signals, cfg["ensemble_weights"])
            edge = (final - float(fair)) * 100.0
            disagree = disagreement_pp(clean_signals)
            confidence = confidence_score(final, edge, disagree, data_quality, cfg["confidence_weights"])
            candidate = Candidate(
                match=match,
                selected_player=selected,
                opponent=opponent,
                selected_market=MarketSide(
                    selected.key, best, med, fair, int(market["bookmakers"]),
                    bookmaker_odds=_bookmaker_odds(selected_books),
                ),
                opponent_market=MarketSide(
                    opponent.key, obest, omed, ofair, int(market["bookmakers"]),
                    bookmaker_odds=_bookmaker_odds(opponent_books),
                ),
                signals=clean_signals,
                final_probability=final,
                market_probability=float(fair),
                edge_pp=edge,
                disagreement_pp=disagree,
                data_quality=data_quality,
                confidence=confidence,
                model_version=cfg["model_version"],
            )
            candidate.match.raw.setdefault("analysis_context", {})[selected.key] = {
                "rank": (rank_a if selected.key == match.player_a.key else rank_b),
                "fatigue": (fatigue_a if selected.key == match.player_a.key else fatigue_b),
                "serve_sample": (serve_seen_a if selected.key == match.player_a.key else serve_seen_b),
                "identity_resolved": not str(selected.key).startswith("name-"),
            }
            candidates.append(candidate)

    write_json(cache_path, enrichment_cache)
    # Only now do execution filters run. The odd range is a selection criterion,
    # never a pre-analysis criterion.
    ranked = rank_candidates(candidates, cfg)
    payload = {
        "date": day,
        "model_version": cfg["model_version"],
        "generated_at_timezone": "America/Sao_Paulo",
        "data_mode": "NO_API",
        "data_sources": ["OddsHarvester/OddsPortal", "JeffSackmann/tennis_atp"],
        "analysis_policy": "ALL_PREMATCH_WITH_MARKET_BEFORE_SELECTION",
        "fixtures_analyzed": len(fixtures),
        "prematch_atp_singles": len(prematch),
        "matches_with_odds": odds_matches,
        "deep_analyzed_matches": deep_matches,
        "fully_analyzed_matches": deep_matches,
        "target_odd_pool_matches": target_odd_matches,
        "matches_without_market": no_market_matches,
        "candidate_sides": len(ranked),
        "h2h_calls": h2h_calls,
        "h2h_budget_effective": effective_h2h_budget,
        "source_requests": getattr(provider, "source_requests", None),
        "unresolved_players": sorted(unresolved_players),
        "data_quality_diagnostics": {
            "surfaces_recovered": recovered_surfaces,
            "stale_rankings_ignored": stale_rankings_ignored,
            "full_analysis_before_odd_filter": True,
        },
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
