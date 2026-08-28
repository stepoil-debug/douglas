from __future__ import annotations

import itertools
from collections import Counter
from typing import Any

from . import betano_execution as base

MAX_OPTIONS = 900
MAX_SEARCH_VISITS = 350_000


def _collect_execution_legs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    legs: list[dict[str, Any]] = []
    seen: set[tuple[Any, str, str]] = set()
    for match in payload.get("all_matches") or []:
        for raw in match.get("eligible_legs") or []:
            leg = base._execution_leg(raw)
            if not leg:
                continue
            key = (
                leg.get("fixture_id"),
                str(leg.get("market") or ""),
                str(leg.get("selection") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            legs.append(leg)

    legs.sort(
        key=lambda row: (
            -int(base._raw_score(row) >= base.ELITE_LEG_SCORE),
            -base._raw_score(row),
            -base._quality_score(row),
            -float(row.get("model_probability") or 0),
        )
    )
    return legs


def _candidate_options(legs: list[dict[str, Any]]) -> list[tuple[float, list[dict[str, Any]], float, str]]:
    options: list[tuple[float, list[dict[str, Any]], float, str]] = []

    for leg in legs:
        total = float(leg["odd"])
        if not (base.MIN_ODD <= total <= base.MAX_ODD):
            continue
        if not base._candidate_probability_ok([leg]) or not base._candidate_raw_scores_ok([leg]):
            continue
        rating, tier = base._quality([leg], total)
        options.append((rating, [leg], total, tier))

    pair_pool = base._pair_pool(legs)
    for left, right in itertools.combinations(pair_pool, 2):
        if left.get("fixture_id") == right.get("fixture_id"):
            continue
        candidate = [left, right]
        if not base._legs_have_required_spacing(candidate):
            continue
        if not base._candidate_raw_scores_ok(candidate):
            continue
        if not base._candidate_probability_ok(candidate):
            continue
        if not base._candidate_cluster_ok(candidate, Counter()):
            continue
        total = float(left["odd"]) * float(right["odd"])
        if not (base.MIN_ODD <= total <= base.MAX_ODD):
            continue
        rating, tier = base._quality(candidate, total)
        options.append((rating, candidate, total, tier))

    # Keep the best version of the exact same set of legs, then search a broad
    # pool. The previous implementation picked greedily; a strong first ticket
    # could block two later tickets even when another valid 3-ticket portfolio
    # existed.
    unique: dict[tuple[tuple[Any, str, str], ...], tuple[float, list[dict[str, Any]], float, str]] = {}
    for option in options:
        sig = base._signature(option[1])
        current = unique.get(sig)
        if current is None or option[0] > current[0]:
            unique[sig] = option
    ranked = sorted(unique.values(), key=lambda item: -item[0])
    return ranked[:MAX_OPTIONS]


def _option_times(legs: list[dict[str, Any]]) -> list[float] | None:
    return base._unique_fixture_times(legs)


def _search_portfolio(
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
    frozen_legs = [leg for ticket in frozen for leg in (ticket.get("legs") or [])]
    used_times = base._unique_fixture_times(frozen_legs) or []
    clusters = Counter(
        base._risk_cluster(leg)
        for ticket in frozen
        for leg in (ticket.get("legs") or [])
    )

    best: list[tuple[float, list[dict[str, Any]], float, str]] = []
    best_rating = float("-inf")
    visits = 0
    solved: list[tuple[float, list[dict[str, Any]], float, str]] | None = None

    def recurse(
        start: int,
        chosen: list[tuple[float, list[dict[str, Any]], float, str]],
        fixtures: set[Any],
        times: list[float],
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

        remaining_needed = needed - len(chosen)
        if len(options) - start < remaining_needed:
            return False

        for index in range(start, len(options)):
            rating, candidate_legs, total, tier = options[index]
            candidate_fixtures = {leg.get("fixture_id") for leg in candidate_legs}
            if None in candidate_fixtures or not candidate_fixtures:
                continue
            if candidate_fixtures & fixtures:
                continue
            if not base._candidate_raw_scores_ok(candidate_legs):
                continue
            if not base._legs_have_required_spacing(candidate_legs, times):
                continue
            if not base._candidate_cluster_ok(candidate_legs, cluster_counts):
                continue
            candidate_times = _option_times(candidate_legs)
            if candidate_times is None:
                continue

            next_clusters = cluster_counts.copy()
            next_clusters.update(base._risk_cluster(leg) for leg in candidate_legs)
            chosen.append((rating, candidate_legs, total, tier))
            if recurse(
                index + 1,
                chosen,
                fixtures | candidate_fixtures,
                times + candidate_times,
                next_clusters,
                rating_sum + rating,
            ):
                return True
            chosen.pop()

        return False

    recurse(0, [], set(used_fixtures), list(used_times), clusters, 0.0)
    return solved if solved is not None else best


def build_betano_tickets(payload: dict[str, Any]) -> list[dict[str, Any]]:
    legs = _collect_execution_legs(payload)
    options = _candidate_options(legs)

    frozen = [dict(ticket) for ticket in (payload.get("previous_published_tickets") or [])][: base.TARGET]
    selected: list[dict[str, Any]] = list(frozen)
    used_ids = {str(ticket.get("ticket_id") or "") for ticket in frozen}

    chosen = _search_portfolio(options, frozen)
    for _, candidate_legs, total, tier in chosen:
        number = next((n for n in range(1, base.TARGET + 1) if f"B{n}" not in used_ids), None)
        if number is None:
            break
        ticket = base._ticket(number, candidate_legs, total, tier)
        selected.append(ticket)
        used_ids.add(f"B{number}")

    selected.sort(key=lambda row: str(row.get("ticket_id") or ""))
    if selected:
        assert base._portfolio_has_unique_fixtures(selected), "Betano ticket portfolio contains repeated fixture"
        assert base._portfolio_has_required_spacing(selected), "Betano ticket portfolio violates 120-minute spacing"
    return selected


def main() -> int:
    # Reuse the mature publication/locking/status logic, replacing only the
    # portfolio builder. This keeps settlement/history compatibility intact.
    base.build_betano_tickets = build_betano_tickets
    result = base.main()

    # Mark the algorithm version explicitly so the dashboard/history makes it
    # clear that the board used backtracking rather than the former greedy pick.
    data_path = base.DASHBOARD / "data.json"
    if data_path.exists():
        payload = base._load(data_path)
        payload["model_version"] = "football-accuracy-betano-v8-backtracking-score84"
        payload["portfolio_search"] = {
            "strategy": "BACKTRACKING",
            "max_options": MAX_OPTIONS,
            "max_search_visits": MAX_SEARCH_VISITS,
            "score_floor": base.MIN_NEW_LEG_SCORE,
            "fixture_exclusivity": True,
            "kickoff_spacing_minutes": 120,
        }
        base._dump(data_path, payload)
        board_date = str(payload.get("board_date") or "")
        if board_date:
            base._dump(base.HISTORY / f"{board_date}.json", payload)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
