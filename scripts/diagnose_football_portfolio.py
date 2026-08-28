from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
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


def main() -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    legs = _collect_execution_legs(payload)
    options = _candidate_options(legs)
    singles = [o for o in options if len(o[1]) == 1]
    pairs = [o for o in options if len(o[1]) == 2]

    global_ok, global_solution = can_build(options, "global")
    anchor_ok, anchor_solution = can_build(options, "anchor")
    relaxed_ok, relaxed_solution = can_build(options, "ticket")

    result = {
        "board_date": payload.get("board_date"),
        "fixtures_found": payload.get("fixtures_found"),
        "fixtures_analyzed": payload.get("fixtures_analyzed"),
        "eligible_execution_legs": len(legs),
        "eligible_execution_fixtures": len({leg.get("fixture_id") for leg in legs}),
        "ticket_options": len(options),
        "single_options_1_50_2_00": len(singles),
        "pair_options_1_50_2_00": len(pairs),
        "three_ticket_portfolio_global_2h": global_ok,
        "three_ticket_portfolio_ticket_start_2h": anchor_ok,
        "three_ticket_portfolio_only_within_ticket_2h": relaxed_ok,
        "global_solution": [option_view(options[i]) for i in global_solution],
        "ticket_start_solution": [option_view(options[i]) for i in anchor_solution],
        "within_ticket_solution": [option_view(options[i]) for i in relaxed_solution],
        "top_options": [option_view(option) for option in options[:12]],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
