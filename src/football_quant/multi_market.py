from __future__ import annotations

import math
import re
from typing import Any

from .api_football import market_prices

# This module expands the engine beyond match-result markets. It intentionally
# starts with full-time totals that can be settled objectively from API-Football
# fixture statistics: goals, corners, yellow cards, shots and shots on target.
# Player props, first-half props and bookmaker-specific card-point systems are
# excluded until they have a deterministic settlement rule.

FAMILY_STABILITY = {
    "GOALS": 0.88,
    "CORNERS": 0.80,
    "CARDS": 0.75,
    "SHOTS": 0.72,
}

MIN_MARKET_PROBABILITY = {
    "GOALS": 0.68,
    "CORNERS": 0.72,
    "CARDS": 0.72,
    "SHOTS": 0.73,
}

SKIP_MARKET_TERMS = (
    "first half", "1st half", "2nd half", "second half", "player", "race to",
    "odd/even", "odd or even", "exact", "asian", "handicap", "minute",
    "red card", "booking points", "card points",
)


def _normal(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _market_probability(price: dict[str, Any]) -> float:
    consensus = float(price.get("consensus_odd") or price.get("odd") or 99)
    if consensus <= 1:
        return 0.0
    # Small margin haircut: implied probability is useful, but not treated as a
    # model probability without adjustment for bookmaker margin.
    return max(0.0, min(0.95, (1.0 / consensus) * 0.97))


def _line(selection: Any) -> tuple[str, float] | None:
    text = _normal(selection).replace(",", ".")
    match = re.search(r"\b(over|under|mais de|menos de)\s*([0-9]+(?:\.[0-9]+)?)\b", text)
    if not match:
        return None
    direction = "over" if match.group(1) in {"over", "mais de"} else "under"
    return direction, float(match.group(2))


def _scope(market_name: str) -> str:
    name = _normal(market_name)
    if any(term in name for term in ("home team", "home total", "home corners", "home cards", "home shots")):
        return "home"
    if any(term in name for term in ("away team", "away total", "away corners", "away cards", "away shots")):
        return "away"
    return "match"


def _family_and_metric(market_name: Any) -> tuple[str, str] | None:
    name = _normal(market_name)
    if any(term in name for term in SKIP_MARKET_TERMS):
        return None
    if "corner" in name:
        return "CORNERS", "corner_kicks"
    # Only yellow-card totals are deterministic across bookmakers. Generic
    # booking-points markets are intentionally excluded above.
    if "yellow card" in name or "yellow cards" in name:
        return "CARDS", "yellow_cards"
    if "shots on target" in name or "shots on goal" in name:
        return "SHOTS", "shots_on_goal"
    if "total shots" in name or ("shots" in name and "target" not in name and "goal" not in name):
        return "SHOTS", "total_shots"
    if any(term in name for term in ("goals over/under", "over/under", "total goals", "goal line")) and "corner" not in name:
        return "GOALS", "goals"
    if "both teams to score" in name or "btts" in name:
        return "GOALS", "btts"
    return None


def _line_allowed(family: str, metric: str, direction: str, line: float) -> bool:
    if family == "GOALS":
        if direction == "over":
            return 0.5 <= line <= 2.5
        return 2.5 <= line <= 5.5
    if family == "CORNERS":
        if direction == "over":
            return 4.5 <= line <= 10.5
        return 8.5 <= line <= 15.5
    if family == "CARDS":
        if direction == "over":
            return 0.5 <= line <= 4.5
        return 3.5 <= line <= 8.5
    if family == "SHOTS":
        if metric == "shots_on_goal":
            return 1.5 <= line <= 11.5
        return 7.5 <= line <= 31.5
    return False


def _selection_label(family: str, metric: str, direction: str, line: float, scope: str) -> str:
    prefix = "Mais de" if direction == "over" else "Menos de"
    number = f"{line:g}"
    if family == "GOALS":
        noun = "gols"
    elif family == "CORNERS":
        noun = "escanteios"
    elif family == "CARDS":
        noun = "cartões amarelos"
    elif metric == "shots_on_goal":
        noun = "chutes no alvo"
    else:
        noun = "chutes"
    if scope == "home":
        return f"Mandante: {prefix} {number} {noun}"
    if scope == "away":
        return f"Visitante: {prefix} {number} {noun}"
    return f"{prefix} {number} {noun}"


def _market_label(family: str, metric: str, scope: str) -> str:
    team = " da equipe" if scope in {"home", "away"} else ""
    if family == "GOALS":
        return "Total de gols" + team
    if family == "CORNERS":
        return "Escanteios" + team
    if family == "CARDS":
        return "Cartões amarelos" + team
    if metric == "shots_on_goal":
        return "Chutes no alvo" + team
    return "Chutes" + team


def _base_leg(
    fixture: dict[str, Any],
    price: dict[str, Any],
    family: str,
    metric: str,
    scope: str,
    direction: str,
    line: float,
) -> dict[str, Any]:
    fixture_info = fixture.get("fixture") or {}
    teams = fixture.get("teams") or {}
    league = fixture.get("league") or {}
    home = str((teams.get("home") or {}).get("name") or "Mandante")
    away = str((teams.get("away") or {}).get("name") or "Visitante")
    probability = _market_probability(price)
    consensus = float(price.get("consensus_odd") or price.get("odd") or 99)
    implied = 1.0 / consensus if consensus > 1 else 1.0
    books = int(price.get("bookmaker_count") or 1)
    reliability = min(0.92, 0.56 + min(books, 8) * 0.045)
    stability = FAMILY_STABILITY[family]
    score = 100 * (0.66 * probability + 0.20 * reliability + 0.14 * stability)
    quotes = {
        str(name): float(value)
        for name, value in (price.get("quotes") or {}).items()
        if float(value) > 1.0
    }
    return {
        "fixture_id": fixture_info.get("id"),
        "kickoff_iso": fixture_info.get("date"),
        "home_team": home,
        "away_team": away,
        "match": f"{home} x {away}",
        "league": league.get("name") or "Liga não informada",
        "country": league.get("country") or "",
        "market": _market_label(family, metric, scope),
        "selection": _selection_label(family, metric, direction, line, scope),
        "raw_market": price.get("market"),
        "raw_selection": price.get("selection"),
        "market_family": family,
        "settlement_metric": metric,
        "settlement_scope": scope,
        "settlement_operator": direction,
        "settlement_line": line,
        "odd": round(float(price.get("odd") or 0), 2),
        "consensus_odd": round(consensus, 2),
        "bookmaker": price.get("bookmaker") or "Referência de mercado",
        "bookmaker_count": books,
        "bookmaker_quotes": quotes,
        "model_probability": round(probability, 4),
        "implied_probability": round(implied, 4),
        "edge": round(probability - implied, 4),
        "score": round(score, 1),
        "signal_source": "MULTI_MARKET_CONSENSUS",
        "risk_flags": [],
        "rationale": (
            f"Mercado {family.lower()} confirmado por {books} bookmaker(s); "
            f"probabilidade implícita ajustada {probability:.0%}; seleção full-time "
            "com regra automática de conferência."
        ),
    }


def _btts_leg(fixture: dict[str, Any], price: dict[str, Any]) -> dict[str, Any] | None:
    selection = _normal(price.get("selection"))
    if selection not in {"yes", "no", "sim", "não", "nao"}:
        return None
    probability = _market_probability(price)
    if probability < MIN_MARKET_PROBABILITY["GOALS"]:
        return None
    fixture_info = fixture.get("fixture") or {}
    teams = fixture.get("teams") or {}
    league = fixture.get("league") or {}
    home = str((teams.get("home") or {}).get("name") or "Mandante")
    away = str((teams.get("away") or {}).get("name") or "Visitante")
    yes = selection in {"yes", "sim"}
    consensus = float(price.get("consensus_odd") or price.get("odd") or 99)
    books = int(price.get("bookmaker_count") or 1)
    reliability = min(0.92, 0.56 + min(books, 8) * 0.045)
    score = 100 * (0.68 * probability + 0.20 * reliability + 0.12 * FAMILY_STABILITY["GOALS"])
    return {
        "fixture_id": fixture_info.get("id"),
        "kickoff_iso": fixture_info.get("date"),
        "home_team": home,
        "away_team": away,
        "match": f"{home} x {away}",
        "league": league.get("name") or "Liga não informada",
        "country": league.get("country") or "",
        "market": "Ambas marcam",
        "selection": "Sim" if yes else "Não",
        "raw_market": price.get("market"),
        "raw_selection": price.get("selection"),
        "market_family": "GOALS",
        "settlement_metric": "btts",
        "settlement_scope": "match",
        "settlement_operator": "yes" if yes else "no",
        "settlement_line": None,
        "odd": round(float(price.get("odd") or 0), 2),
        "consensus_odd": round(consensus, 2),
        "bookmaker": price.get("bookmaker") or "Referência de mercado",
        "bookmaker_count": books,
        "bookmaker_quotes": {
            str(name): float(value) for name, value in (price.get("quotes") or {}).items() if float(value) > 1.0
        },
        "model_probability": round(probability, 4),
        "implied_probability": round(1.0 / consensus, 4) if consensus > 1 else 1.0,
        "edge": round(probability - (1.0 / consensus if consensus > 1 else 1.0), 4),
        "score": round(score, 1),
        "signal_source": "MULTI_MARKET_CONSENSUS",
        "risk_flags": [],
        "rationale": f"BTTS validado pelo consenso de {books} bookmaker(s), sem depender do vencedor.",
    }


def build_multi_market_legs(
    fixture: dict[str, Any],
    odds_row: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not odds_row:
        return []
    candidates: list[dict[str, Any]] = []
    for price in market_prices(odds_row):
        odd = float(price.get("odd") or 99)
        books = int(price.get("bookmaker_count") or 1)
        if not (1.05 <= odd <= 1.60):
            continue
        # A thin market at a meaningful price is too fragile for the selective engine.
        if books < 2 and odd > 1.25:
            continue
        classification = _family_and_metric(price.get("market"))
        if not classification:
            continue
        family, metric = classification
        probability = _market_probability(price)
        if probability < MIN_MARKET_PROBABILITY[family]:
            continue

        if metric == "btts":
            leg = _btts_leg(fixture, price)
            if leg:
                candidates.append(leg)
            continue

        parsed = _line(price.get("selection"))
        if not parsed:
            continue
        direction, line = parsed
        if not _line_allowed(family, metric, direction, line):
            continue
        scope = _scope(str(price.get("market") or ""))
        candidates.append(_base_leg(fixture, price, family, metric, scope, direction, line))

    # Keep the strongest quote for each canonical proposition.
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for leg in candidates:
        key = (_normal(leg.get("market")), _normal(leg.get("selection")))
        current = unique.get(key)
        if current is None or float(leg.get("score") or 0) > float(current.get("score") or 0):
            unique[key] = leg
    return sorted(
        unique.values(),
        key=lambda row: (-float(row.get("score") or 0), -float(row.get("model_probability") or 0)),
    )


def family_counts(legs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"GOALS": 0, "CORNERS": 0, "CARDS": 0, "SHOTS": 0, "RESULT": 0}
    for leg in legs:
        family = str(leg.get("market_family") or "RESULT").upper()
        counts[family] = counts.get(family, 0) + 1
    return counts
