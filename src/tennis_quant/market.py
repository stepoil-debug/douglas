from __future__ import annotations

from statistics import median


def no_vig_probability(odd_a: float, odd_b: float) -> tuple[float, float]:
    if odd_a <= 1 or odd_b <= 1:
        raise ValueError("Decimal odds must be greater than 1")
    imp_a, imp_b = 1 / odd_a, 1 / odd_b
    total = imp_a + imp_b
    return imp_a / total, imp_b / total


def consensus_market(home: dict[str, str | float], away: dict[str, str | float]) -> dict[str, float | int | None]:
    paired: list[tuple[float, float]] = []
    for book in sorted(set(home) & set(away)):
        try:
            a, b = float(home[book]), float(away[book])
        except (TypeError, ValueError):
            continue
        if a > 1 and b > 1:
            paired.append((a, b))

    if not paired:
        return {
            "home_best": None, "away_best": None,
            "home_median": None, "away_median": None,
            "home_fair": None, "away_fair": None,
            "bookmakers": 0,
        }

    home_odds = [x[0] for x in paired]
    away_odds = [x[1] for x in paired]
    fair = [no_vig_probability(a, b) for a, b in paired]
    return {
        "home_best": max(home_odds),
        "away_best": max(away_odds),
        "home_median": median(home_odds),
        "away_median": median(away_odds),
        "home_fair": median([x[0] for x in fair]),
        "away_fair": median([x[1] for x in fair]),
        "bookmakers": len(paired),
    }
