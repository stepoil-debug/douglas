from __future__ import annotations

import itertools
import math
from collections import Counter
from typing import Any

from . import betano_execution as base
from .betano_execution_v8 import _collect_execution_legs

MAX_OPTIONS = 2200
MAX_SEARCH_VISITS = 450_000
MIN_TRIPLE_COMBINED_PROBABILITY = 0.64
MIN_TRIPLE_LEG_PROBABILITY = 0.80
PORTFOLIO_CLUSTER_CAPS = {"GOALS_UNDER": 3, "RESULT": 1}


def _cluster_ok(candidate_legs: list[dict[str, Any]], portfolio: Counter[str]) -> bool:
    clusters = [base._risk_cluster(leg) for leg in candidate_legs]
    # Diversification: a single ticket may not contain two separate under-goals
    # theses. Across B1/B2/B3 at most one such leg per ticket is allowed.
    if clusters.count("GOALS_UNDER") > 1:
        return False
    proposed = portfolio.copy()
    proposed.update(clusters)
    return all(proposed[name] <= cap for name, cap in PORTFOLIO_CLUSTER_CAPS.items())


def _probability_ok(legs: list[dict[str, Any]]) -> bool:
    probabilities = [float(leg.get("model_probability") or 0) for leg in legs]
    if not probabilities:
        return False
    combined = math.prod(probabilities)
    if len(legs) == 1:
        return probabilities[0] >= base.MIN_SINGLE_PROBABILITY
    if len(legs) == 2:
        return min(probabilities) >= 0.80 and combined >= base.MIN_PAIR_COMBINED_PROBABILITY
    if len(legs) == 3:
        return min(probabilities) >= MIN_TRIPLE_LEG_PROBABILITY and combined >= MIN_TRIPLE_COMBINED_PROBABILITY
    return False


def _make_options(legs: list[dict[str, Any]]) -> list[tuple[float, list[dict[str, Any]], float, str]]:
    options: list[tuple[float, list[dict[str, Any]], float, str]] = []

    # Singles are retained if the market itself already reaches the requested odd.
    for leg in legs:
        total = float(leg["odd"])
        if base.MIN_ODD <= total <= base.MAX_ODD and _probability_ok([leg]):
            rating, tier = base._quality([leg], total)
            options.append((rating, [leg], total, tier))

    # Limit repeated market variants from the same fixture while keeping enough
    # depth to find time-diverse high-score combinations.
    pair_pool = base._pair_pool(legs)

    for left, right in itertools.combinations(pair_pool, 2):
        candidate = [left, right]
        fixture_ids = {leg.get("fixture_id") for leg in candidate}
        if None in fixture_ids or len(fixture_ids) != 2:
            continue
        if not base._legs_have_required_spacing(candidate):
            continue
        if not base._candidate_raw_scores_ok(candidate) or not _probability_ok(candidate):
            continue
        if not _cluster_ok(candidate, Counter()):
            continue
        total = float(left["odd"]) * float(right["odd"])
        if not (base.MIN_ODD <= total <= base.MAX_ODD):
            continue
        rating, tier = base._quality(candidate, total)
        options.append((rating, candidate, total, tier))

    # The old engine stopped at two legs. With accuracy-first selections the
    # Betano odds are commonly 1.05-1.24, making 1.50-2.00 unreachable without
    # sacrificing probability. Three strong legs solve that without lowering
    # the individual score floor.
    for first, second, third in itertools.combinations(pair_pool, 3):
        candidate = [first, second, third]
        fixture_ids = {leg.get("fixture_id") for leg in candidate}
        if None in fixture_ids or len(fixture_ids) != 3:
            continue
        total = float(first["odd"]) * float(second["odd"]) * float(third["odd"])
        if not (base.MIN_ODD <= total <= base.MAX_ODD):
            continue
        if not base._legs_have_required_spacing(candidate):
            continue
        if not base._candidate_raw_scores_ok(candidate) or not _probability_ok(candidate):
            continue
        if not _cluster_ok(candidate, Counter()):
            continue
        rating, tier = base._quality(candidate, total)
        # Prefer higher combined probability within the same quality region.
        rating += math.prod(float(leg.get("model_probability") or 0) for leg in candidate) * 12
        options.append((rating, candidate, total, tier))

    unique: dict[tuple[tuple[Any, str, str], ...], tuple[float, list[dict[str, Any]], float, str]] = {}
    for option in options:
        signature = base._signature(option[1])
        current = unique.get(signature)
        if current is None or option[0] > current[0]:
            unique[signature] = option
    return sorted(unique.values(), key=lambda item: -item[0])[:MAX_OPTIONS]


def _search(
    options: list[tuple[float, list[dict[str, Any]], float, str]],
    frozen: list[dict[str, Any]],
) -> list[tuple[float, list[dict[str, Any]], float, str]]:
    needed = max(0, base.TARGET - len(frozen))
    if needed == 0:
        return []

    used_fixtures = {
        leg.get("fixture_id")
        for ticket in frozen
        for leg in (ticket.get("legs") or [])
        if leg.get("fixture_id") is not None
    }
    clusters = Counter(
        base._risk_cluster(leg)
        for ticket in frozen
        for leg in (ticket.get("legs") or [])
    )
    visits = 0
    best: list[tuple[float, list[dict[str, Any]], float, str]] = []
    best_rating = float("-inf")
    solved: list[tuple[float, list[dict[str, Any]], float, str]] | None = None

    def recurse(
        start: int,
        chosen: list[tuple[float, list[dict[str, Any]], float, str]],
        fixtures: set[Any],
        cluster_counts: Counter[str],
        rating_sum: float,
    ) -> bool:
        nonlocal visits, best, best_rating, solved
        visits += 1
        if visits > MAX_SEARCH_VISITS:
            return False

        if len(chosen) > len(best) or (len(chosen) == len(best) and rating_sum > best_rating):
            best = list(chosen)
            best_rating = rating_sum
        if len(chosen) >= needed:
            solved = list(chosen)
            return True

        for index in range(start, len(options)):
            rating, candidate_legs, total, tier = options[index]
            candidate_fixtures = {leg.get("fixture_id") for leg in candidate_legs}
            if None in candidate_fixtures or not candidate_fixtures or candidate_fixtures & fixtures:
                continue
            if not base._candidate_raw_scores_ok(candidate_legs) or not _probability_ok(candidate_legs):
                continue
            # The 120-minute rule applies to the games composing each ticket.
            # Cross-ticket fixture exclusivity remains absolute.
            if not base._legs_have_required_spacing(candidate_legs):
                continue
            if not _cluster_ok(candidate_legs, cluster_counts):
                continue
            next_clusters = cluster_counts.copy()
            next_clusters.update(base._risk_cluster(leg) for leg in candidate_legs)
            chosen.append((rating, candidate_legs, total, tier))
            if recurse(
                index + 1,
                chosen,
                fixtures | candidate_fixtures,
                next_clusters,
                rating_sum + rating,
            ):
                return True
            chosen.pop()
        return False

    recurse(0, [], set(used_fixtures), clusters, 0.0)
    return solved if solved is not None else best


def build_betano_tickets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    legs = _collect_execution_legs(payload)
    options = _make_options(legs)
    frozen = [dict(ticket) for ticket in (payload.get("previous_published_tickets") or [])][: base.TARGET]
    selected = list(frozen)
    used_ids = {str(ticket.get("ticket_id") or "") for ticket in frozen}

    for _, candidate_legs, total, tier in _search(options, frozen):
        number = next((n for n in range(1, base.TARGET + 1) if f"B{n}" not in used_ids), None)
        if number is None:
            break
        selected.append(base._ticket(number, candidate_legs, total, tier))
        used_ids.add(f"B{number}")

    selected.sort(key=lambda row: str(row.get("ticket_id") or ""))
    if selected:
        assert base._portfolio_has_unique_fixtures(selected), "Portfolio contains repeated fixture"
        assert all(base._legs_have_required_spacing(ticket.get("legs") or []) for ticket in selected), "Ticket violates 120-minute internal spacing"
    return selected


def _spacing_valid(tickets: list[dict[str, Any]]) -> bool:
    return bool(tickets) and all(base._legs_have_required_spacing(ticket.get("legs") or []) for ticket in tickets)


def main() -> int:
    base.build_betano_tickets = build_betano_tickets
    result = base.main()

    data_path = base.DASHBOARD / "data.json"
    status_path = base.DASHBOARD / "run_status.json"
    if data_path.exists():
        payload = base._load(data_path)
        tickets = payload.get("tickets") or []
        spacing_valid = _spacing_valid(tickets)
        payload["model_version"] = "football-accuracy-betano-v9-three-leg-score84"
        payload["max_ticket_legs"] = 3
        payload["triple_probability_floor"] = MIN_TRIPLE_COMBINED_PROBABILITY
        payload["portfolio_search"] = {
            "strategy": "BACKTRACKING_1_TO_3_LEGS",
            "max_options": MAX_OPTIONS,
            "score_floor": base.MIN_NEW_LEG_SCORE,
            "triple_min_leg_probability": MIN_TRIPLE_LEG_PROBABILITY,
            "triple_combined_probability_floor": MIN_TRIPLE_COMBINED_PROBABILITY,
            "fixture_exclusivity_across_tickets": True,
            "kickoff_spacing_minutes_within_ticket": 120,
        }
        payload["kickoff_spacing"] = {
            "enabled": True,
            "minimum_minutes": 120,
            "scope": "WITHIN_EACH_TICKET",
            "valid": spacing_valid,
            "rule": "Dentro de cada bilhete, jogos diferentes devem iniciar com pelo menos 120 minutos de diferença; nenhum jogo pode se repetir entre B1/B2/B3.",
        }
        criteria = payload.setdefault("criteria", {})
        criteria["max_legs"] = 3
        criteria["ticket_odd_range"] = "1.50-2.00"
        base._dump(data_path, payload)
        board_date = str(payload.get("board_date") or "")
        if board_date:
            base._dump(base.HISTORY / f"{board_date}.json", payload)

        status = base._load(status_path) if status_path.exists() else {}
        status["kickoff_spacing_valid"] = spacing_valid
        status["kickoff_spacing_scope"] = "WITHIN_EACH_TICKET"
        status["max_ticket_legs"] = 3
        status["model_version"] = payload["model_version"]
        if len(tickets) == base.TARGET:
            status["message"] = "3 bilhetes publicados com 1 a 3 pernas; toda perna tem score bruto >=84, jogos não se repetem entre bilhetes e cada múltipla respeita 120 minutos entre jogos diferentes."
        base._dump(status_path, status)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
