from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from tennis_quant.domain import Candidate, MarketSide
from tennis_quant.features import h2h_rate, recent_win_rate
from tennis_quant.market import consensus_market
from tennis_quant.prediction import confidence_score, disagreement_pp, weighted_probability
from tennis_quant.ratings import RatingStore
from tennis_quant.selection import rank_candidates
from tennis_quant.storage import write_json, write_snapshot


def _extract_home_away(raw: dict[str, Any]) -> tuple[dict, dict]:
    home_away = raw.get("Home/Away", {}) if isinstance(raw, dict) else {}
    home = home_away.get("Home", {}) or {}
    away = home_away.get("Away", {}) or {}
    return home, away


def analyze_day(provider, target_date: date, cfg: dict, root: Path, h2h_budget: int = 40) -> dict[str, Any]:
    fixtures = provider.fixtures(target_date)
    odds_by_match = provider.odds(target_date)
    ratings = RatingStore(root / "data" / "state" / "ratings.json")
    candidates: list[Candidate] = []
    h2h_calls = 0

    for match in fixtures:
        if "Atp Singles" not in match.event_type:
            continue
        raw_odds = odds_by_match.get(match.match_id, {})
        home, away = _extract_home_away(raw_odds)
        market = consensus_market(home, away)
        if not market["bookmakers"]:
            continue

        elo_a, surf_a = ratings.probability(match.player_a.key, match.player_b.key, match.surface)
        context = {}
        if h2h_calls < h2h_budget:
            try:
                context = provider.h2h(match.player_a.key, match.player_b.key)
                h2h_calls += 1
            except Exception:
                context = {}

        a_recent, a_seen = recent_win_rate(context.get("firstPlayerResults", []) or [], match.player_a.key)
        b_recent, b_seen = recent_win_rate(context.get("secondPlayerResults", []) or [], match.player_b.key)
        a_h2h, h_seen = h2h_rate(context.get("H2H", []) or [], match.player_a.key)

        # H2H is deliberately low influence in V1; it is folded into recent-form only when evidence exists.
        if h_seen:
            a_recent = 0.85 * a_recent + 0.15 * a_h2h
        form_a = a_recent / max(a_recent + b_recent, 1e-9)
        form_b = 1.0 - form_a
        data_quality = min(1.0, 0.45 + 0.05 * min(a_seen + b_seen, 10) + 0.02 * min(int(market["bookmakers"]), 10))

        sides = [
            (match.player_a, match.player_b, market["home_best"], market["home_median"], market["home_fair"], market["away_best"], market["away_median"], market["away_fair"], elo_a, surf_a, form_a),
            (match.player_b, match.player_a, market["away_best"], market["away_median"], market["away_fair"], market["home_best"], market["home_median"], market["home_fair"], 1-elo_a, 1-surf_a, form_b),
        ]
        for selected, opponent, best, med, fair, obest, omed, ofair, elo, surf, form in sides:
            if best is None or fair is None:
                continue
            signals = {"market": fair, "elo": elo, "surface_elo": surf, "recent_form": form}
            final = weighted_probability(signals, cfg["ensemble_weights"])
            edge = (final - fair) * 100.0
            disagree = disagreement_pp(signals)
            confidence = confidence_score(final, edge, disagree, data_quality, cfg["confidence_weights"])
            candidates.append(Candidate(
                match=match,
                selected_player=selected,
                opponent=opponent,
                selected_market=MarketSide(selected.key, best, med, fair, int(market["bookmakers"])),
                opponent_market=MarketSide(opponent.key, obest, omed, ofair, int(market["bookmakers"])),
                signals=signals,
                final_probability=final,
                market_probability=fair,
                edge_pp=edge,
                disagreement_pp=disagree,
                data_quality=data_quality,
                confidence=confidence,
                model_version=cfg["model_version"],
            ))

    ranked = rank_candidates(candidates, cfg)
    day = target_date.isoformat()
    payload = {
        "date": day,
        "model_version": cfg["model_version"],
        "fixtures_analyzed": len(fixtures),
        "candidate_sides": len(ranked),
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
