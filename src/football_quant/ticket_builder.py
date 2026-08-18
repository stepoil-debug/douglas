from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from typing import Any

from .api_football import market_prices

MIN_TICKET_ODD = 1.50
MAX_TICKET_ODD = 2.00
TARGET_TICKETS = 3

PRIORITY_COUNTRIES = {
    "England", "Spain", "Italy", "Germany", "France", "Portugal", "Netherlands",
    "Belgium", "Brazil", "Argentina", "USA", "Mexico", "Turkey", "Greece",
    "Scotland", "Switzerland", "Austria", "Denmark", "Norway", "Sweden",
}

LOW_SIGNAL_LEAGUE_TERMS = (
    "friendly", "friendlies", "u17", "u18", "u19", "u20", "u21", "reserve",
    "youth", "women friendly", "amateur",
)


def pct(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace("%", "").replace(",", ".")
    try:
        number = float(raw)
    except ValueError:
        return None
    if number > 1:
        number /= 100.0
    return max(0.0, min(1.0, number))


def _normal(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().casefold())


def _league_priority(fixture: dict[str, Any]) -> int:
    league = fixture.get("league") or {}
    name = _normal(league.get("name"))
    country = str(league.get("country") or "")
    if any(term in name for term in LOW_SIGNAL_LEAGUE_TERMS):
        return -10
    score = 0
    if country in PRIORITY_COUNTRIES:
        score += 3
    if str(league.get("type") or "").casefold() == "league":
        score += 2
    if any(term in name for term in ("champions", "europa", "conference", "premier", "serie a", "la liga", "bundesliga", "ligue 1", "brasile")):
        score += 3
    return score


def _prediction_parts(prediction: dict[str, Any] | None) -> dict[str, Any]:
    if not prediction:
        return {}
    predictions = prediction.get("predictions") or {}
    percent = predictions.get("percent") or {}
    return {
        "home": pct(percent.get("home")) or 0.0,
        "draw": pct(percent.get("draw")) or 0.0,
        "away": pct(percent.get("away")) or 0.0,
        "advice": str(predictions.get("advice") or ""),
        "under_over": str(predictions.get("under_over") or ""),
        "winner": (predictions.get("winner") or {}).get("name"),
        "win_or_draw": bool(predictions.get("win_or_draw")),
        "goals": predictions.get("goals") or {},
        "comparison": prediction.get("comparison") or {},
    }


def _comparison_strength(prediction: dict[str, Any] | None, side: str) -> float:
    if not prediction:
        return 0.5
    comparison = prediction.get("comparison") or {}
    values: list[float] = []
    for key in ("form", "att", "def", "poisson_distribution", "h2h", "goals", "total"):
        block = comparison.get(key) or {}
        value = pct(block.get(side))
        if value is not None:
            values.append(value)
    return sum(values) / len(values) if values else 0.5


def _find_price(prices: list[dict[str, Any]], market_terms: tuple[str, ...], selection_terms: tuple[str, ...]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for price in prices:
        market = _normal(price.get("market"))
        selection = _normal(price.get("selection"))
        if not any(term in market for term in market_terms):
            continue
        if not any(term == selection or term in selection for term in selection_terms):
            continue
        candidates.append(price)
    if not candidates:
        return None
    return max(candidates, key=lambda row: float(row.get("odd") or 0))


def _team_names(fixture: dict[str, Any]) -> tuple[str, str]:
    teams = fixture.get("teams") or {}
    return str((teams.get("home") or {}).get("name") or "Mandante"), str((teams.get("away") or {}).get("name") or "Visitante")


def _base_leg(fixture: dict[str, Any], market: str, selection: str, price: dict[str, Any], model_probability: float, rationale: str, strength: float) -> dict[str, Any]:
    home, away = _team_names(fixture)
    league = fixture.get("league") or {}
    fixture_info = fixture.get("fixture") or {}
    odd = float(price.get("odd") or 0)
    implied = 1.0 / odd if odd > 1 else 1.0
    edge = model_probability - implied
    score = 100 * (
        0.52 * model_probability
        + 0.22 * max(0.0, min(1.0, strength))
        + 0.16 * max(0.0, min(1.0, 0.5 + edge))
        + 0.10 * max(0.0, min(1.0, (_league_priority(fixture) + 2) / 10))
    )
    return {
        "fixture_id": fixture_info.get("id"),
        "kickoff_iso": fixture_info.get("date"),
        "home_team": home,
        "away_team": away,
        "match": f"{home} x {away}",
        "league": league.get("name") or "Liga não informada",
        "country": league.get("country") or "",
        "market": market,
        "selection": selection,
        "odd": round(odd, 2),
        "bookmaker": price.get("bookmaker") or "Referência de mercado",
        "model_probability": round(model_probability, 4),
        "implied_probability": round(implied, 4),
        "edge": round(edge, 4),
        "score": round(score, 1),
        "rationale": rationale,
    }


def build_legs(fixture: dict[str, Any], prediction: dict[str, Any] | None, odds_row: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not prediction or not odds_row or _league_priority(fixture) < 0:
        return []
    parts = _prediction_parts(prediction)
    prices = market_prices(odds_row)
    if not prices:
        return []
    home, away = _team_names(fixture)
    home_p = float(parts.get("home") or 0)
    away_p = float(parts.get("away") or 0)
    draw_p = float(parts.get("draw") or 0)
    side = "home" if home_p >= away_p else "away"
    side_p = home_p if side == "home" else away_p
    side_name = home if side == "home" else away
    strength = _comparison_strength(prediction, side)
    legs: list[dict[str, Any]] = []

    # Match winner: only when model and comparative strength agree strongly.
    if side_p >= 0.59 and strength >= 0.52:
        selection_terms = ("home", "1") if side == "home" else ("away", "2")
        price = _find_price(prices, ("match winner", "1x2", "winner"), selection_terms)
        if price and 1.32 <= float(price["odd"]) <= 2.05:
            legs.append(_base_leg(
                fixture, "Vencedor da partida", side_name, price,
                min(0.84, side_p * (0.90 + strength * 0.12)),
                f"Modelo aponta {side_name} com {side_p:.0%}; força comparativa {strength:.0%}.",
                strength,
            ))

    # Double chance for the stronger side. This is a high-accuracy building block for doubles.
    dc_probability = min(0.94, side_p + draw_p)
    if dc_probability >= 0.74:
        if side == "home":
            selection_terms = ("home or draw", "home/draw", "1x", "1 or x")
            selection_label = f"{home} ou empate"
        else:
            selection_terms = ("away or draw", "draw/away", "x2", "x or 2")
            selection_label = f"{away} ou empate"
        price = _find_price(prices, ("double chance",), selection_terms)
        if price and 1.12 <= float(price["odd"]) <= 1.58:
            legs.append(_base_leg(
                fixture, "Dupla chance", selection_label, price,
                dc_probability,
                f"Cobertura do lado mais forte: vitória/empate soma {dc_probability:.0%} no modelo.",
                max(strength, 0.62),
            ))

    under_over = _normal(parts.get("under_over"))
    # Over 1.5: require the provider to lean to goals or both sides to have non-trivial win mass.
    over15_conf = 0.0
    if "over 2.5" in under_over or "over 3.5" in under_over:
        over15_conf = 0.84
    elif "over 1.5" in under_over:
        over15_conf = 0.79
    elif max(home_p, away_p) >= 0.63 and draw_p <= 0.28:
        over15_conf = 0.72
    if over15_conf:
        price = _find_price(
            prices,
            ("goals over/under", "over/under", "total goals", "goals"),
            ("over 1.5", "over 1,5"),
        )
        if price and 1.10 <= float(price["odd"]) <= 1.55:
            legs.append(_base_leg(
                fixture, "Total de gols", "Mais de 1.5 gols", price,
                over15_conf,
                f"Projeção de gols da API: {parts.get('under_over') or 'viés ofensivo'}; proteção na linha 1.5.",
                0.72,
            ))

    # Under 4.5: conservative only when API does not project a very high-scoring match.
    under45_conf = 0.0
    if any(term in under_over for term in ("under 2.5", "under 3.5", "under 4.5")):
        under45_conf = 0.86
    elif "over 2.5" in under_over:
        under45_conf = 0.74
    elif "over 3.5" not in under_over and "over 4.5" not in under_over:
        under45_conf = 0.78
    if under45_conf:
        price = _find_price(
            prices,
            ("goals over/under", "over/under", "total goals", "goals"),
            ("under 4.5", "under 4,5"),
        )
        if price and 1.08 <= float(price["odd"]) <= 1.50:
            legs.append(_base_leg(
                fixture, "Total de gols", "Menos de 4.5 gols", price,
                under45_conf,
                "Linha conservadora usada apenas quando a projeção não indica placar extremo.",
                0.75,
            ))

    # Favorite to score at least once. Market names differ among bookmakers, so support common variants.
    if side_p >= 0.60:
        market_terms = ("home team total", "home goals", "team total") if side == "home" else ("away team total", "away goals", "team total")
        price = _find_price(prices, market_terms, ("over 0.5", "over 0,5", "1 or more"))
        if price and 1.08 <= float(price["odd"]) <= 1.45:
            legs.append(_base_leg(
                fixture, "Gol da equipe", f"{side_name} marca 1+ gol", price,
                min(0.90, 0.76 + max(0.0, side_p - 0.60) * 0.55),
                f"Equipe mais forte tem {side_p:.0%} de vitória e recebe linha protegida de 1 gol.",
                strength,
            ))

    # Remove weaker duplicates for the same market/selection.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for leg in legs:
        key = (_normal(leg["market"]), _normal(leg["selection"]))
        current = unique.get(key)
        if current is None or float(leg["score"]) > float(current["score"]):
            unique[key] = leg
    return sorted(unique.values(), key=lambda row: (-float(row["score"]), -float(row["model_probability"])))


def rank_fixture_candidates(fixtures: list[dict[str, Any]], odds_by_fixture: dict[int, dict[str, Any]], max_candidates: int = 14) -> list[dict[str, Any]]:
    rows: list[tuple[float, dict[str, Any]]] = []
    for fixture in fixtures:
        info = fixture.get("fixture") or {}
        status = str((info.get("status") or {}).get("short") or "")
        if status not in {"NS", "TBD"}:
            continue
        try:
            fixture_id = int(info.get("id"))
        except (TypeError, ValueError):
            continue
        odds_row = odds_by_fixture.get(fixture_id)
        if not odds_row:
            continue
        prices = market_prices(odds_row)
        if not prices:
            continue
        league_score = _league_priority(fixture)
        if league_score < 0:
            continue
        market_bonus = min(8, len({p["market"] for p in prices}) / 3)
        winner_prices = [float(p["odd"]) for p in prices if _normal(p["market"]) in {"match winner", "1x2", "winner"}]
        favorite = min(winner_prices) if winner_prices else 99
        favorite_bonus = 6 if 1.30 <= favorite <= 2.10 else 0
        rows.append((league_score * 10 + market_bonus + favorite_bonus, fixture))
    rows.sort(key=lambda item: (-item[0], str((item[1].get("fixture") or {}).get("date") or "")))
    return [row for _, row in rows[:max(1, max_candidates)]]


def _ticket_from_legs(ticket_id: int, legs: list[dict[str, Any]], quality_tier: str) -> dict[str, Any]:
    total_odd = math.prod(float(leg["odd"]) for leg in legs)
    probability = math.prod(float(leg["model_probability"]) for leg in legs)
    if len({leg["fixture_id"] for leg in legs}) < len(legs):
        probability *= 0.92  # correlation penalty for same-event combinations
    score = sum(float(leg["score"]) for leg in legs) / len(legs)
    return {
        "ticket_id": f"B{ticket_id}",
        "profile": ("CONSERVADOR" if ticket_id == 1 else "EQUILIBRADO" if ticket_id == 2 else "SELETIVO"),
        "quality_tier": quality_tier,
        "total_odd": round(total_odd, 2),
        "estimated_probability": round(max(0.0, min(1.0, probability)), 4),
        "score": round(score, 1),
        "legs": legs,
        "status": "PENDING",
        "reason": "Bilhete montado com mercados confirmados na API e filtros de consistência do modelo.",
    }


def build_tickets(legs: list[dict[str, Any]], target: int = TARGET_TICKETS) -> list[dict[str, Any]]:
    if not legs:
        return []
    # Strong legs first; avoid using low-confidence legs unless required to reach the requested ticket count.
    ordered = sorted(legs, key=lambda row: (-float(row["score"]), -float(row["model_probability"]), float(row["odd"])))
    candidates: list[tuple[float, list[dict[str, Any]], str]] = []

    # Singles in target range.
    for leg in ordered:
        odd = float(leg["odd"])
        prob = float(leg["model_probability"])
        if MIN_TICKET_ODD <= odd <= MAX_TICKET_ODD and prob >= 0.59 and float(leg["score"]) >= 61:
            candidates.append((float(leg["score"]) + prob * 12, [leg], "STRICT" if prob >= 0.64 else "FALLBACK"))

    # Two-leg multiples. Prefer separate matches to reduce correlation.
    for left, right in itertools.combinations(ordered[:24], 2):
        if left["fixture_id"] == right["fixture_id"]:
            continue
        total = float(left["odd"]) * float(right["odd"])
        if not (MIN_TICKET_ODD <= total <= MAX_TICKET_ODD):
            continue
        min_prob = min(float(left["model_probability"]), float(right["model_probability"]))
        avg_score = (float(left["score"]) + float(right["score"])) / 2
        if min_prob < 0.68 or avg_score < 61:
            continue
        combined_prob = float(left["model_probability"]) * float(right["model_probability"])
        rating = avg_score + combined_prob * 18 - abs(total - 1.72) * 3
        candidates.append((rating, [left, right], "STRICT" if min_prob >= 0.74 else "FALLBACK"))

    candidates.sort(key=lambda item: -item[0])
    selected: list[dict[str, Any]] = []
    seen_sets: set[tuple[tuple[Any, str, str], ...]] = set()
    fixture_exposure: dict[Any, int] = {}

    def signature(candidate_legs: list[dict[str, Any]]) -> tuple[tuple[Any, str, str], ...]:
        return tuple(sorted((leg["fixture_id"], str(leg["market"]), str(leg["selection"])) for leg in candidate_legs))

    # Pass 1: diversified selections, max two appearances per fixture.
    for _, candidate_legs, tier in candidates:
        sig = signature(candidate_legs)
        if sig in seen_sets:
            continue
        fixtures = {leg["fixture_id"] for leg in candidate_legs}
        if any(fixture_exposure.get(fid, 0) >= 2 for fid in fixtures):
            continue
        selected.append(_ticket_from_legs(len(selected) + 1, candidate_legs, tier))
        seen_sets.add(sig)
        for fid in fixtures:
            fixture_exposure[fid] = fixture_exposure.get(fid, 0) + 1
        if len(selected) >= target:
            return selected

    # Pass 2: if the slate is small, allow repeated fixture exposure but never duplicate the same ticket.
    for _, candidate_legs, tier in candidates:
        sig = signature(candidate_legs)
        if sig in seen_sets:
            continue
        selected.append(_ticket_from_legs(len(selected) + 1, candidate_legs, tier))
        seen_sets.add(sig)
        if len(selected) >= target:
            break
    return selected


def summarize_match(fixture: dict[str, Any], prediction: dict[str, Any] | None, legs: list[dict[str, Any]]) -> dict[str, Any]:
    info = fixture.get("fixture") or {}
    league = fixture.get("league") or {}
    home, away = _team_names(fixture)
    parts = _prediction_parts(prediction)
    best_leg = legs[0] if legs else None
    return {
        "fixture_id": info.get("id"),
        "kickoff_iso": info.get("date"),
        "home_team": home,
        "away_team": away,
        "match": f"{home} x {away}",
        "league": league.get("name") or "Liga não informada",
        "country": league.get("country") or "",
        "home_probability": parts.get("home"),
        "draw_probability": parts.get("draw"),
        "away_probability": parts.get("away"),
        "advice": parts.get("advice") or "",
        "under_over": parts.get("under_over") or "",
        "best_market": best_leg,
        "eligible_legs": legs,
        "decision": "USABLE" if legs else "REJECTED",
        "score": best_leg.get("score") if best_leg else 0,
    }
