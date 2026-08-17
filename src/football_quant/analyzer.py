from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .api_football import extract_match_winner_odds

TOP_LIMIT = 6
MIN_ODD = 1.50
MAX_ODD = 2.00
MIN_PROBABILITY = 0.58
MIN_EDGE = 0.03
MIN_SCORE = 70.0

PRIORITY_COUNTRIES = {
    "England", "Spain", "Italy", "Germany", "France", "Portugal", "Netherlands",
    "Belgium", "Brazil", "Argentina", "USA", "Mexico", "Turkey", "Greece",
    "Scotland", "Switzerland", "Austria", "Denmark", "Norway", "Sweden",
}

PRIORITY_LEAGUE_TERMS = (
    "premier league", "la liga", "serie a", "bundesliga", "ligue 1", "primeira liga",
    "eredivisie", "champions league", "europa league", "conference league", "copa",
    "brasileirao", "paulista", "carioca", "mls", "liga profesional", "super lig",
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


def _league_priority(fixture: dict[str, Any]) -> int:
    league = fixture.get("league") or {}
    name = str(league.get("name") or "").lower()
    country = str(league.get("country") or "")
    score = 0
    if country in PRIORITY_COUNTRIES:
        score += 2
    if any(term in name for term in PRIORITY_LEAGUE_TERMS):
        score += 3
    if str(league.get("type") or "").lower() == "league":
        score += 1
    return score


def eligible_fixtures(fixtures: list[dict[str, Any]], max_candidates: int = 18) -> list[dict[str, Any]]:
    rows = []
    for item in fixtures:
        fixture = item.get("fixture") or {}
        status = (fixture.get("status") or {}).get("short")
        if status not in {"NS", "TBD"}:
            continue
        teams = item.get("teams") or {}
        if not (teams.get("home") or {}).get("id") or not (teams.get("away") or {}).get("id"):
            continue
        rows.append(item)

    rows.sort(
        key=lambda row: (
            -_league_priority(row),
            str((row.get("fixture") or {}).get("date") or ""),
            int((row.get("fixture") or {}).get("id") or 0),
        )
    )
    return rows[: max(1, max_candidates)]


def _comparison_strength(prediction: dict[str, Any], side: str) -> float:
    comparison = prediction.get("comparison") or {}
    values = []
    for key in ("form", "att", "def", "poisson_distribution", "h2h", "goals", "total"):
        block = comparison.get(key) or {}
        value = pct(block.get(side))
        if value is not None:
            values.append(value)
    return sum(values) / len(values) if values else 0.5


def _kickoff_parts(value: str | None) -> tuple[str, str]:
    if not value:
        return "", ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.date().isoformat(), dt.strftime("%H:%M")
    except ValueError:
        return value[:10], value[11:16]


def analyze_fixture(
    fixture_row: dict[str, Any],
    prediction: dict[str, Any] | None,
    odds_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    fixture = fixture_row.get("fixture") or {}
    league = fixture_row.get("league") or {}
    teams = fixture_row.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    odds = extract_match_winner_odds(odds_rows)

    base = {
        "fixture_id": fixture.get("id"),
        "kickoff_iso": fixture.get("date"),
        "league": league.get("name") or "Liga não informada",
        "country": league.get("country") or "",
        "home_team": home.get("name") or "Mandante",
        "away_team": away.get("name") or "Visitante",
        "home_team_id": home.get("id"),
        "away_team_id": away.get("id"),
        "status": "REJECTED",
        "reasons": [],
    }
    board_date, kickoff = _kickoff_parts(fixture.get("date"))
    base["date"] = board_date
    base["kickoff"] = kickoff

    if not prediction:
        base["reasons"] = ["Sem previsão disponível na API-Football"]
        return base
    if not odds:
        base["reasons"] = ["Sem mercado 1X2 disponível"]
        return base

    percents = ((prediction.get("predictions") or {}).get("percent") or {})
    home_prob = pct(percents.get("home")) or 0.0
    away_prob = pct(percents.get("away")) or 0.0
    draw_prob = pct(percents.get("draw")) or 0.0
    side = "home" if home_prob >= away_prob else "away"
    probability = home_prob if side == "home" else away_prob
    pick = base["home_team"] if side == "home" else base["away_team"]
    odd = (odds.get("best") or {}).get(side)

    base.update(
        {
            "pick": pick,
            "pick_side": side.upper(),
            "odd": odd,
            "probability": probability,
            "draw_probability": draw_prob,
            "advice": (prediction.get("predictions") or {}).get("advice") or "",
            "bookmakers": odds.get("bookmakers") or {},
        }
    )

    if not odd:
        base["reasons"] = ["Odd do lado previsto indisponível"]
        return base

    implied = 1.0 / odd
    edge = probability - implied
    comparison = _comparison_strength(prediction, side)
    score = 0.0
    score += min(40.0, max(0.0, (probability - 0.45) / 0.30 * 40.0))
    score += min(25.0, max(0.0, edge / 0.15 * 25.0))
    score += min(20.0, max(0.0, (comparison - 0.45) / 0.35 * 20.0))
    if MIN_ODD <= odd <= MAX_ODD:
        score += 10.0
    if draw_prob <= 0.25:
        score += 5.0
    score = round(max(0.0, min(100.0, score)), 1)

    reasons = []
    if probability >= MIN_PROBABILITY:
        reasons.append(f"Probabilidade do modelo {probability:.0%}")
    else:
        reasons.append(f"Probabilidade abaixo do corte ({probability:.0%})")
    if edge >= MIN_EDGE:
        reasons.append(f"Edge estimado +{edge:.1%}")
    else:
        reasons.append(f"Edge insuficiente ({edge:.1%})")
    if MIN_ODD <= odd <= MAX_ODD:
        reasons.append(f"Odd dentro da faixa {MIN_ODD:.2f}–{MAX_ODD:.2f}")
    else:
        reasons.append(f"Odd fora da faixa ({odd:.2f})")
    reasons.append(f"Força comparativa {comparison:.0%}")

    approved = (
        MIN_ODD <= odd <= MAX_ODD
        and probability >= MIN_PROBABILITY
        and edge >= MIN_EDGE
        and score >= MIN_SCORE
    )

    base.update(
        {
            "implied_probability": implied,
            "edge": edge,
            "comparison_strength": comparison,
            "score": score,
            "decision": "APPROVED" if approved else "REJECTED",
            "status": "PENDING" if approved else "REJECTED",
            "reasons": reasons,
        }
    )
    return base


def rank_analyses(rows: list[dict[str, Any]], top_limit: int = TOP_LIMIT) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    approved = [row for row in rows if row.get("decision") == "APPROVED"]
    rejected = [row for row in rows if row.get("decision") != "APPROVED"]
    approved.sort(key=lambda row: (-float(row.get("score") or 0), -float(row.get("edge") or 0), float(row.get("odd") or 99)))
    rejected.sort(key=lambda row: (-float(row.get("score") or 0), -float(row.get("probability") or 0)))
    approved = approved[: max(1, top_limit)]
    for index, row in enumerate(approved, start=1):
        row["rank"] = index
    return approved, rejected
