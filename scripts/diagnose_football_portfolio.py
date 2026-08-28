from __future__ import annotations

import itertools
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from src.football_quant import betano_execution as base
from src.football_quant.betano_execution_v8 import _candidate_options, _collect_execution_legs

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dashboard" / "data.json"


def fixture_set(option: tuple[float, list[dict[str, Any]], float, str]) -> set[Any]:
    return {leg.get("fixture_id") for leg in option[1]}


def times(option: tuple[float, list[dict[str, Any]], float, str]) -> list[float]:
    return base._unique_fixture_times(option[1]) or []


def anchor(option: tuple[float, list[dict[str, Any]], float, str]) -> float | None:
    values = times(option)
    return min(values) if values else None


def compatible(
    option: tuple[float, list[dict[str, Any]], float, str],
    used_fixtures: set[Any],
    used_times: list[float],
    used_anchors: list[float],
    clusters: Counter[str],
    mode: str,
) -> bool:
    legs = option[1]
    fixtures = fixture_set(option)
    if None in fixtures or fixtures & used_fixtures:
        return False
    if not base._candidate_cluster_ok(legs, clusters):
        return False
    if mode == "global" and not base._legs_have_required_spacing(legs, used_times):
        return False
    if mode == "anchor":
        current = anchor(option)
        if current is None or any(abs(current - old) < base.MIN_KICKOFF_GAP_SECONDS for old in used_anchors):
            return False
    return True


def can_build(options, mode: str, target: int = 3) -> tuple[bool, list[int]]:
    solution: list[int] = []
    visits = 0

    def rec(start, chosen, used_fixtures, used_times, used_anchors, clusters):
        nonlocal visits, solution
        visits += 1
        if visits > 300_000:
            return False
        if len(chosen) >= target:
            solution = list(chosen)
            return True
        for idx in range(start, len(options)):
            option = options[idx]
            if not compatible(option, used_fixtures, used_times, used_anchors, clusters, mode):
                continue
            option_times = times(option)
            current_anchor = anchor(option)
            next_clusters = clusters.copy()
            next_clusters.update(base._risk_cluster(leg) for leg in option[1])
            if rec(
                idx + 1,
                chosen + [idx],
                used_fixtures | fixture_set(option),
                used_times + option_times,
                used_anchors + ([current_anchor] if current_anchor is not None else []),
                next_clusters,
            ):
                return True
        return False

    ok = rec(0, [], set(), [], [], Counter())
    return ok, solution


def option_view(option):
    rating, legs, total, tier = option
    return {
        "rating": round(rating, 2),
        "total_odd": round(total, 2),
        "tier": tier,
        "legs": [
            {
                "fixture_id": leg.get("fixture_id"),
                "match": leg.get("match"),
                "kickoff": leg.get("kickoff_iso"),
                "selection": leg.get("selection"),
                "odd": leg.get("odd"),
                "probability": leg.get("model_probability"),
                "score": leg.get("score"),
                "family": base._family(leg),
            }
            for leg in legs
        ],
    }


def leg_view(leg):
    return {
        "fixture_id": leg.get("fixture_id"),
        "match": leg.get("match"),
        "kickoff": leg.get("kickoff_iso"),
        "selection": leg.get("selection"),
        "family": base._family(leg),
        "odd": leg.get("odd"),
        "probability": leg.get("model_probability"),
        "score": leg.get("score"),
    }


def combo_view(combo):
    total = math.prod(float(leg.get("odd") or 0) for leg in combo)
    combined_probability = math.prod(float(leg.get("model_probability") or 0) for leg in combo)
    return {
        "total_odd": round(total, 3),
        "combined_probability": round(combined_probability, 4),
        "legs": [leg_view(leg) for leg in combo],
    }


def main() -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    legs = _collect_execution_legs(payload)
    options = _candidate_options(legs)
    singles = [o for o in options if len(o[1]) == 1]
    pairs = [o for o in options if len(o[1]) == 2]

    odd_values = sorted(float(leg.get("odd") or 0) for leg in legs)
    pair_raw = []
    pair_prob = []
    pair_spacing = []
    pair_cluster = []
    same_fixture_pair_raw = []
    same_fixture_pair_cross_family = []

    for left, right in itertools.combinations(legs, 2):
        total = float(left["odd"]) * float(right["odd"])
        in_range = base.MIN_ODD <= total <= base.MAX_ODD
        if left.get("fixture_id") == right.get("fixture_id"):
            if in_range:
                same_fixture_pair_raw.append((left, right))
                if base._family(left) != base._family(right):
                    same_fixture_pair_cross_family.append((left, right))
            continue
        if not in_range:
            continue
        combo = [left, right]
        pair_raw.append(combo)
        if base._candidate_probability_ok(combo):
            pair_prob.append(combo)
        else:
            continue
        if base._legs_have_required_spacing(combo):
            pair_spacing.append(combo)
        else:
            continue
        if base._candidate_cluster_ok(combo, Counter()):
            pair_cluster.append(combo)

    triple_raw = []
    triple_spacing = []
    triple_prob58 = []
    for combo_tuple in itertools.combinations(legs, 3):
        combo = list(combo_tuple)
        fixtures = {leg.get("fixture_id") for leg in combo}
        if None in fixtures or len(fixtures) != 3:
            continue
        total = math.prod(float(leg["odd"]) for leg in combo)
        if not (base.MIN_ODD <= total <= base.MAX_ODD):
            continue
        triple_raw.append(combo)
        combined_probability = math.prod(float(leg.get("model_probability") or 0) for leg in combo)
        if min(float(leg.get("model_probability") or 0) for leg in combo) >= 0.80 and combined_probability >= 0.58:
            triple_prob58.append(combo)
        if base._legs_have_required_spacing(combo):
            triple_spacing.append(combo)

    global_ok, global_solution = can_build(options, "global")
    anchor_ok, anchor_solution = can_build(options, "anchor")
    relaxed_ok, relaxed_solution = can_build(options, "ticket")

    result = {
        "board_date": payload.get("board_date"),
        "fixtures_found": payload.get("fixtures_found"),
        "fixtures_analyzed": payload.get("fixtures_analyzed"),
        "eligible_execution_legs": len(legs),
        "eligible_execution_fixtures": len({leg.get("fixture_id") for leg in legs}),
        "betano_odds": {
            "min": round(min(odd_values), 3) if odd_values else None,
            "median": round(median(odd_values), 3) if odd_values else None,
            "max": round(max(odd_values), 3) if odd_values else None,
            "ge_1_20": sum(1 for value in odd_values if value >= 1.20),
            "ge_1_25": sum(1 for value in odd_values if value >= 1.25),
            "ge_1_30": sum(1 for value in odd_values if value >= 1.30),
            "ge_1_50": sum(1 for value in odd_values if value >= 1.50),
        },
        "ticket_options": len(options),
        "single_options_1_50_2_00": len(singles),
        "pair_options_1_50_2_00": len(pairs),
        "pair_diagnostics": {
            "raw_odd_range_different_fixtures": len(pair_raw),
            "after_probability": len(pair_prob),
            "after_2h_spacing": len(pair_spacing),
            "after_cluster_guard": len(pair_cluster),
        },
        "same_fixture_pair_diagnostics": {
            "raw_odd_range": len(same_fixture_pair_raw),
            "cross_market_family": len(same_fixture_pair_cross_family),
            "examples": [combo_view(list(combo)) for combo in same_fixture_pair_cross_family[:5]],
        },
        "triple_diagnostics": {
            "raw_odd_range_three_fixtures": len(triple_raw),
            "with_all_three_2h_apart": len(triple_spacing),
            "min_leg_prob_80_combined_prob_58": len(triple_prob58),
            "examples": [combo_view(combo) for combo in triple_prob58[:5]],
        },
        "three_ticket_portfolio_global_2h": global_ok,
        "three_ticket_portfolio_ticket_start_2h": anchor_ok,
        "three_ticket_portfolio_only_within_ticket_2h": relaxed_ok,
        "global_solution": [option_view(options[i]) for i in global_solution],
        "ticket_start_solution": [option_view(options[i]) for i in anchor_solution],
        "within_ticket_solution": [option_view(options[i]) for i in relaxed_solution],
        "top_legs": [leg_view(leg) for leg in legs[:12]],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
