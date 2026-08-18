from __future__ import annotations

import itertools
import math
import re
from typing import Any

from .api_football import market_prices

MIN_TICKET_ODD = 1.50
MAX_TICKET_ODD = 2.00
TARGET_TICKETS = 3
TARGET_CENTER = 1.72

# Accuracy / risk controls. These values intentionally make the engine more
# selective instead of forcing three tickets when the board is weak.
MAX_MODEL_MARKET_GAP = 0.12
EXTREME_PROBABILITY_EPSILON = 0.01
CUP_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY = 0.80
GENERAL_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY = 0.69

PRIORITY_COUNTRIES = {
    "England", "Spain", "Italy", "Germany", "France", "Portugal", "Netherlands",
    "Belgium", "Brazil", "Argentina", "USA", "Mexico", "Turkey", "Greece",
    "Scotland", "Switzerland", "Austria", "Denmark", "Norway", "Sweden",
}

LOW_SIGNAL_LEAGUE_TERMS = (
    "friendly", "friendlies", "u17", "u18", "u19", "u20", "u21", "reserve",
    "youth", "women friendly", "amateur",
)

CUP_TERMS = (
    " cup", "cup ", "copa", "taça", "taca", "pokal", "coupe", "coppa",
    "beker", "pokalen", "cupa", "kubok",
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


def _is_cup_fixture(fixture: dict[str, Any]) -> bool:
    league = fixture.get("league") or {}
    name = f" {_normal(league.get('name'))} "
    league_type = _normal(league.get("type"))
    return league_type == "cup" or any(term in name for term in CUP_TERMS)


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
    if any(term in name for term in (
        "champions", "europa", "conference", "premier", "serie a", "la liga",
        "bundesliga", "ligue 1", "brasile", "libertadores", "sudamericana",
    )):
        score += 3
    # Cup matches remain eligible, but receive a mild ranking penalty because
    # rotation/motivation variance is structurally higher than in league play.
    if _is_cup_fixture(fixture):
        score -= 1
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


def _prediction_risk_flags(parts: dict[str, Any]) -> list[str]:
    probabilities = [float(parts.get(key) or 0.0) for key in ("home", "draw", "away")]
    flags: list[str] = []
    total = sum(probabilities)
    if total and not 0.97 <= total <= 1.03:
        flags.append("PROBABILITY_SUM_ANOMALY")
    if probabilities and (
        min(probabilities) <= EXTREME_PROBABILITY_EPSILON
        or max(probabilities) >= 1.0 - EXTREME_PROBABILITY_EPSILON
    ):
        flags.append("EXTREME_PROBABILITY")
    # API feeds sometimes emit coarse 0/50/50 or 50/50/0 distributions. They
    # are useful directionally, but must not be treated as a 95-100% signal.
    rounded = sorted(round(value, 2) for value in probabilities)
    if rounded in ([0.0, 0.5, 0.5], [0.0, 0.0, 1.0]):
        flags.append("COARSE_PROBABILITY")
    return flags


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


def _selection_matches(selection: str, term: str) -> bool:
    selection = _normal(selection)
    term = _normal(term)
    if term in {"1", "2", "x", "1x", "x2", "12"}:
        return selection == term
    return selection == term or term in selection


def _find_price(
    prices: list[dict[str, Any]],
    market_terms: tuple[str, ...],
    selection_terms: tuple[str, ...],
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for price in prices:
        market = _normal(price.get("market"))
        selection = _normal(price.get("selection"))
        if not any(term in market for term in market_terms):
            continue
        if not any(_selection_matches(selection, term) for term in selection_terms):
            continue
        candidates.append(price)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (int(row.get("bookmaker_count") or 0), float(row.get("odd") or 0)),
    )


def _team_names(fixture: dict[str, Any]) -> tuple[str, str]:
    teams = fixture.get("teams") or {}
    return (
        str((teams.get("home") or {}).get("name") or "Mandante"),
        str((teams.get("away") or {}).get("name") or "Visitante"),
    )


def _market_probability(price: dict[str, Any]) -> tuple[float, float]:
    consensus = float(price.get("consensus_odd") or price.get("odd") or 99)
    probability = max(0.0, min(0.94, (1.0 / consensus) * 0.97)) if consensus > 1 else 0.0
    books = int(price.get("bookmaker_count") or 1)
    reliability = min(0.88, 0.58 + min(books, 6) * 0.05)
    return probability, reliability


def _calibrated_probability(model_probability: float, price: dict[str, Any], model_weight: float = 0.74) -> float:
    market_probability, _ = _market_probability(price)
    if market_probability <= 0:
        return model_probability
    return max(0.0, min(0.94, model_weight * model_probability + (1.0 - model_weight) * market_probability))


def _calibration_weight(
    raw_model_probability: float,
    price: dict[str, Any],
    base_weight: float,
    prediction_flags: list[str],
) -> tuple[float, list[str], float]:
    market_probability, _ = _market_probability(price)
    risk_flags = list(prediction_flags)
    weight = base_weight
    penalty = 0.0
    if prediction_flags:
        weight = min(weight, 0.25)
        penalty += 4.0
    if market_probability > 0:
        gap = abs(raw_model_probability - market_probability)
        if gap > MAX_MODEL_MARKET_GAP:
            risk_flags.append("MODEL_MARKET_DISAGREEMENT")
            weight = min(weight, 0.35)
            penalty += min(7.0, (gap - MAX_MODEL_MARKET_GAP) * 35.0)
    return weight, sorted(set(risk_flags)), penalty


def _base_leg(
    fixture: dict[str, Any],
    market: str,
    selection: str,
    price: dict[str, Any],
    model_probability: float,
    rationale: str,
    strength: float,
    signal_source: str = "MODEL+MARKET",
    risk_flags: list[str] | None = None,
    risk_penalty: float = 0.0,
) -> dict[str, Any]:
    home, away = _team_names(fixture)
    league = fixture.get("league") or {}
    fixture_info = fixture.get("fixture") or {}
    odd = float(price.get("odd") or 0)
    consensus_odd = float(price.get("consensus_odd") or odd or 99)
    implied = 1.0 / consensus_odd if consensus_odd > 1 else 1.0
    edge = model_probability - implied
    book_count = int(price.get("bookmaker_count") or 1)
    consensus_strength = min(1.0, 0.52 + book_count * 0.07)
    score = 100 * (
        0.48 * model_probability
        + 0.20 * max(0.0, min(1.0, strength))
        + 0.12 * max(0.0, min(1.0, consensus_strength))
        + 0.12 * max(0.0, min(1.0, 0.5 + edge))
        + 0.08 * max(0.0, min(1.0, (_league_priority(fixture) + 2) / 10))
    )
    score = max(0.0, score - max(0.0, risk_penalty))
    quotes = {
        str(book): float(value)
        for book, value in (price.get("quotes") or {price.get("bookmaker") or "Bookmaker": odd}).items()
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
        "market": market,
        "selection": selection,
        "odd": round(odd, 2),
        "consensus_odd": round(consensus_odd, 2),
        "bookmaker": price.get("bookmaker") or "Referência de mercado",
        "bookmaker_count": book_count,
        "bookmaker_quotes": quotes,
        "model_probability": round(model_probability, 4),
        "implied_probability": round(implied, 4),
        "edge": round(edge, 4),
        "score": round(score, 1),
        "signal_source": signal_source,
        "risk_flags": sorted(set(risk_flags or [])),
        "rationale": rationale,
    }


def _market_only_legs(fixture: dict[str, Any], prices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    legs: list[dict[str, Any]] = []
    cup_fixture = _is_cup_fixture(fixture)
    for price in prices:
        market = _normal(price.get("market"))
        selection = _normal(price.get("selection"))
        odd = float(price.get("odd") or 99)
        books = int(price.get("bookmaker_count") or 1)
        market_p, reliability = _market_probability(price)
        if not (1.07 <= odd <= 1.58):
            continue
        if books < 2 and odd > 1.30:
            continue
        if market_p < 0.65:
            continue

        canonical_market = ""
        canonical_selection = str(price.get("selection") or "")
        min_probability = 0.68
        risk_flags: list[str] = []
        risk_penalty = 0.0
        if "double chance" in market and selection in {
            "home or draw", "home/draw", "1x", "1 or x",
            "away or draw", "draw/away", "x2", "x or 2",
        }:
            canonical_market = "Dupla chance"
            min_probability = (
                CUP_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY
                if cup_fixture
                else GENERAL_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY
            )
            if cup_fixture:
                risk_flags.append("CUP_VOLATILITY")
                risk_penalty += 2.0
        elif any(term in market for term in ("goals over/under", "over/under", "total goals")) and selection in {"over 1.5", "over 1,5"}:
            canonical_market = "Total de gols"
            canonical_selection = "Mais de 1.5 gols"
            min_probability = 0.70
        elif any(term in market for term in ("goals over/under", "over/under", "total goals")) and selection in {"under 4.5", "under 4,5"}:
            canonical_market = "Total de gols"
            canonical_selection = "Menos de 4.5 gols"
            min_probability = 0.70
        elif "team total" in market and selection in {"over 0.5", "over 0,5"}:
            canonical_market = "Gol da equipe"
            min_probability = 0.70
        else:
            continue

        if market_p < min_probability:
            continue
        legs.append(
            _base_leg(
                fixture,
                canonical_market,
                canonical_selection,
                price,
                market_p,
                f"Consenso de {books} bookmaker(s); probabilidade implícita ajustada {market_p:.0%}. Fallback de mercado para cobertura estatística limitada.",
                reliability,
                signal_source="MARKET_CONSENSUS",
                risk_flags=risk_flags,
                risk_penalty=risk_penalty,
            )
        )
    return legs


def build_legs(
    fixture: dict[str, Any],
    prediction: dict[str, Any] | None,
    odds_row: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not odds_row or _league_priority(fixture) < 0:
        return []
    prices = market_prices(odds_row)
    if not prices:
        return []
    legs: list[dict[str, Any]] = _market_only_legs(fixture, prices)
    if not prediction:
        return _dedupe_legs(legs)

    parts = _prediction_parts(prediction)
    prediction_flags = _prediction_risk_flags(parts)
    home, away = _team_names(fixture)
    home_p = float(parts.get("home") or 0)
    away_p = float(parts.get("away") or 0)
    draw_p = float(parts.get("draw") or 0)
    side = "home" if home_p >= away_p else "away"
    side_p = home_p if side == "home" else away_p
    side_name = home if side == "home" else away
    strength = _comparison_strength(prediction, side)

    if side_p >= 0.58 and strength >= 0.50:
        selection_terms = ("home", "1") if side == "home" else ("away", "2")
        price = _find_price(prices, ("match winner", "1x2", "winner"), selection_terms)
        if price and 1.30 <= float(price["odd"]) <= 2.05:
            weight, risk_flags, penalty = _calibration_weight(side_p, price, 0.74, prediction_flags)
            calibrated = _calibrated_probability(side_p, price, weight)
            if calibrated >= 0.56:
                legs.append(_base_leg(
                    fixture, "Vencedor da partida", side_name, price, calibrated,
                    f"Modelo {side_p:.0%} para {side_name}; força comparativa {strength:.0%}; calibrado pelo consenso das casas.",
                    strength, risk_flags=risk_flags, risk_penalty=penalty,
                ))

    dc_model = min(0.95, side_p + draw_p)
    if dc_model >= 0.72:
        if side == "home":
            selection_terms = ("home or draw", "home/draw", "1x", "1 or x")
            selection_label = f"{home} ou empate"
        else:
            selection_terms = ("away or draw", "draw/away", "x2", "x or 2")
            selection_label = f"{away} ou empate"
        price = _find_price(prices, ("double chance",), selection_terms)
        if price and 1.08 <= float(price["odd"]) <= 1.60:
            market_p, _ = _market_probability(price)
            # A coarse/extreme model must not override a weak cup market. This
            # specifically prevents 0/50/50 from becoming an artificial 95%.
            risky_cup = _is_cup_fixture(fixture) and bool(prediction_flags)
            if not (risky_cup and market_p < CUP_DOUBLE_CHANCE_MIN_MARKET_PROBABILITY):
                weight, risk_flags, penalty = _calibration_weight(dc_model, price, 0.70, prediction_flags)
                if _is_cup_fixture(fixture):
                    risk_flags = sorted(set(risk_flags + ["CUP_VOLATILITY"]))
                    penalty += 2.0
                calibrated = _calibrated_probability(dc_model, price, weight)
                legs.append(_base_leg(
                    fixture, "Dupla chance", selection_label, price, calibrated,
                    f"Vitória/empate do lado mais forte soma {dc_model:.0%} no modelo; confiança calibrada pelo consenso real das casas.",
                    max(strength, 0.62), risk_flags=risk_flags, risk_penalty=penalty,
                ))

    under_over = _normal(parts.get("under_over"))
    over15_model = 0.0
    if "over 3.5" in under_over or "over 2.5" in under_over:
        over15_model = 0.84
    elif "over 1.5" in under_over:
        over15_model = 0.79
    elif max(home_p, away_p) >= 0.62 and draw_p <= 0.29:
        over15_model = 0.72
    if over15_model:
        price = _find_price(prices, ("goals over/under", "over/under", "total goals"), ("over 1.5", "over 1,5"))
        if price and 1.07 <= float(price["odd"]) <= 1.58:
            weight, risk_flags, penalty = _calibration_weight(over15_model, price, 0.68, prediction_flags)
            calibrated = _calibrated_probability(over15_model, price, weight)
            legs.append(_base_leg(
                fixture, "Total de gols", "Mais de 1.5 gols", price, calibrated,
                f"Projeção da API: {parts.get('under_over') or 'viés ofensivo'}; linha 1.5 confirmada pelo mercado.",
                0.74, risk_flags=risk_flags, risk_penalty=penalty,
            ))

    under45_model = 0.0
    if any(term in under_over for term in ("under 2.5", "under 3.5", "under 4.5")):
        under45_model = 0.87
    elif "over 2.5" in under_over:
        under45_model = 0.75
    elif "over 3.5" not in under_over and "over 4.5" not in under_over:
        under45_model = 0.79
    if under45_model:
        price = _find_price(prices, ("goals over/under", "over/under", "total goals"), ("under 4.5", "under 4,5"))
        if price and 1.06 <= float(price["odd"]) <= 1.52:
            weight, risk_flags, penalty = _calibration_weight(under45_model, price, 0.68, prediction_flags)
            calibrated = _calibrated_probability(under45_model, price, weight)
            legs.append(_base_leg(
                fixture, "Total de gols", "Menos de 4.5 gols", price, calibrated,
                "Teto de gols validado pela projeção estatística e pelo consenso de mercado.",
                0.77, risk_flags=risk_flags, risk_penalty=penalty,
            ))

    if side_p >= 0.59:
        market_terms = (("home team total", "home goals", "team total") if side == "home" else ("away team total", "away goals", "team total"))
        price = _find_price(prices, market_terms, ("over 0.5", "over 0,5", "1 or more"))
        if price and 1.06 <= float(price["odd"]) <= 1.48:
            raw_model = min(0.91, 0.75 + max(0.0, side_p - 0.59) * 0.60)
            weight, risk_flags, penalty = _calibration_weight(raw_model, price, 0.68, prediction_flags)
            calibrated = _calibrated_probability(raw_model, price, weight)
            legs.append(_base_leg(
                fixture, "Gol da equipe", f"{side_name} marca 1+ gol", price, calibrated,
                f"Equipe mais forte tem {side_p:.0%} de vitória; linha reduzida para 1 gol e confirmada no mercado.",
                strength, risk_flags=risk_flags, risk_penalty=penalty,
            ))

    return _dedupe_legs(legs)


def _dedupe_legs(legs: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        book_depth = max((int(p.get("bookmaker_count") or 1) for p in prices), default=1)
        market_bonus = min(10.0, len({p["market"] for p in prices}) / 2.5)
        depth_bonus = min(8.0, book_depth * 1.2)
        winner_prices = [float(p["consensus_odd"]) for p in prices if _normal(p["market"]) in {"match winner", "1x2", "winner"}]
        favorite = min(winner_prices) if winner_prices else 99
        favorite_bonus = 7 if 1.25 <= favorite <= 2.10 else 0
        rows.append((league_score * 10 + market_bonus + depth_bonus + favorite_bonus, fixture))
    rows.sort(key=lambda item: (-item[0], str((item[1].get("fixture") or {}).get("date") or "")))
    return [row for _, row in rows[:max(1, max_candidates)]]


def _price_candidate_at_common_bookmaker(candidate_legs: list[dict[str, Any]]) -> tuple[str, float, list[dict[str, Any]]] | None:
    quote_maps = [leg.get("bookmaker_quotes") or {} for leg in candidate_legs]
    if not quote_maps or any(not quotes for quotes in quote_maps):
        return None
    common = set(quote_maps[0])
    for quotes in quote_maps[1:]:
        common.intersection_update(quotes)
    options: list[tuple[float, float, str, list[dict[str, Any]]]] = []
    for bookmaker in common:
        priced: list[dict[str, Any]] = []
        total = 1.0
        for leg, quotes in zip(candidate_legs, quote_maps):
            leg_odd = float(quotes[bookmaker])
            total *= leg_odd
            copy = dict(leg)
            copy["odd"] = round(leg_odd, 2)
            copy["bookmaker"] = bookmaker
            priced.append(copy)
        if MIN_TICKET_ODD <= total <= MAX_TICKET_ODD:
            options.append((abs(total - TARGET_CENTER), -total, bookmaker, priced))
    if not options:
        return None
    options.sort(key=lambda item: (item[0], item[1], item[2]))
    _, neg_total, bookmaker, priced = options[0]
    return bookmaker, -neg_total, priced


def _ticket_from_legs(ticket_id: int, legs: list[dict[str, Any]], bookmaker: str, total_odd: float, quality_tier: str) -> dict[str, Any]:
    probability = math.prod(float(leg["model_probability"]) for leg in legs)
    score = sum(float(leg["score"]) for leg in legs) / len(legs)
    return {
        "ticket_id": f"B{ticket_id}",
        "profile": "CONSERVADOR" if ticket_id == 1 else "EQUILIBRADO" if ticket_id == 2 else "SELETIVO",
        "quality_tier": quality_tier,
        "bookmaker": bookmaker,
        "total_odd": round(total_odd, 2),
        "estimated_probability": round(max(0.0, min(1.0, probability)), 4),
        "score": round(score, 1),
        "legs": legs,
        "status": "PENDING",
        "reason": "Bilhete com partidas exclusivas: nenhum jogo pode aparecer em outro bilhete do mesmo ciclo.",
    }


def _candidate_quality(legs: list[dict[str, Any]], total_odd: float) -> tuple[float, str]:
    min_probability = min(float(leg["model_probability"]) for leg in legs)
    combined_probability = math.prod(float(leg["model_probability"]) for leg in legs)
    avg_score = sum(float(leg["score"]) for leg in legs) / len(legs)
    sources = {str(leg.get("signal_source") or "") for leg in legs}
    risk_count = sum(len(leg.get("risk_flags") or []) for leg in legs)
    if all(source == "MODEL+MARKET" for source in sources) and min_probability >= 0.73 and risk_count == 0:
        tier, bonus = "STRICT", 5.0
    elif min_probability >= 0.69 and risk_count <= 1:
        tier, bonus = "STRONG", 2.5
    else:
        tier, bonus = "CONSENSUS", 0.0
    rating = avg_score + combined_probability * 22 + bonus - abs(total_odd - TARGET_CENTER) * 2.5 - risk_count * 1.5
    return rating, tier


def build_tickets(legs: list[dict[str, Any]], target: int = TARGET_TICKETS) -> list[dict[str, Any]]:
    if not legs:
        return []
    ordered = sorted(legs, key=lambda row: (-float(row["score"]), -float(row["model_probability"]), float(row["odd"])))
    candidates: list[tuple[float, list[dict[str, Any]], str, str, float]] = []

    for leg in ordered:
        priced = _price_candidate_at_common_bookmaker([leg])
        if not priced or float(leg["model_probability"]) < 0.54 or float(leg["score"]) < 57:
            continue
        bookmaker, total, priced_legs = priced
        rating, tier = _candidate_quality(priced_legs, total)
        candidates.append((rating, priced_legs, tier, bookmaker, total))

    for left, right in itertools.combinations(ordered[:30], 2):
        if left["fixture_id"] == right["fixture_id"]:
            continue
        min_probability = min(float(left["model_probability"]), float(right["model_probability"]))
        avg_score = (float(left["score"]) + float(right["score"])) / 2
        if min_probability < 0.65 or avg_score < 57:
            continue
        priced = _price_candidate_at_common_bookmaker([left, right])
        if not priced:
            continue
        bookmaker, total, priced_legs = priced
        rating, tier = _candidate_quality(priced_legs, total)
        candidates.append((rating, priced_legs, tier, bookmaker, total))

    candidates.sort(key=lambda item: -item[0])
    selected: list[dict[str, Any]] = []
    seen_sets: set[tuple[tuple[Any, str, str], ...]] = set()
    used_fixtures: set[Any] = set()

    def signature(candidate_legs: list[dict[str, Any]]) -> tuple[tuple[Any, str, str], ...]:
        return tuple(sorted((leg["fixture_id"], str(leg["market"]), str(leg["selection"])) for leg in candidate_legs))

    # Strict portfolio diversification: once a fixture is used in one ticket,
    # it cannot appear in any other ticket from the same analysis cycle.
    for _, candidate_legs, tier, bookmaker, total in candidates:
        sig = signature(candidate_legs)
        if sig in seen_sets:
            continue
        fixtures = {leg["fixture_id"] for leg in candidate_legs}
        if fixtures & used_fixtures:
            continue
        selected.append(_ticket_from_legs(len(selected) + 1, candidate_legs, bookmaker, total, tier))
        seen_sets.add(sig)
        used_fixtures.update(fixtures)
        if len(selected) >= target:
            break

    # Never relax the diversification rule just to fabricate three tickets.
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
        "home_probability": parts.get("home") if prediction else None,
        "draw_probability": parts.get("draw") if prediction else None,
        "away_probability": parts.get("away") if prediction else None,
        "advice": parts.get("advice") or "",
        "under_over": parts.get("under_over") or "",
        "prediction_available": bool(prediction),
        "prediction_risk_flags": _prediction_risk_flags(parts) if prediction else [],
        "best_market": best_leg,
        "eligible_legs": legs,
        "decision": "USABLE" if legs else "REJECTED",
        "score": best_leg.get("score") if best_leg else 0,
    }
