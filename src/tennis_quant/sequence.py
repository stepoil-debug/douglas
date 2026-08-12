from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tennis_quant.storage import write_json

TARGET_GAMES = 6
MIN_PROBABILITY = 0.50
MIN_GAP_MINUTES = 210


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _candidate_rows(board: dict[str, Any]) -> list[dict[str, Any]]:
    return (
        list(board.get("approved", []) or [])
        + list(board.get("shadow", []) or [])
        + list(board.get("rejected", []) or [])
    )


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _quality(row: dict[str, Any]) -> float:
    return (
        _number(row.get("final_probability")) * 100.0
        + _number(row.get("confidence")) * 0.35
        + _number(row.get("data_quality")) * 12.0
        + max(-5.0, min(15.0, _number(row.get("edge_pp")))) * 0.15
    )


def _best_per_match(board: dict[str, Any]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in _candidate_rows(board):
        match = row.get("match") or {}
        match_id = str(match.get("match_id") or "").strip()
        probability = _number(row.get("final_probability"), -1.0)
        odd = _number(row.get("odd") or (row.get("selected_market") or {}).get("best_odd"), -1.0)
        if not match_id or probability < MIN_PROBABILITY or odd <= 1.0:
            continue
        previous = best.get(match_id)
        if previous is None:
            best[match_id] = row
            continue
        previous_probability = _number(previous.get("final_probability"), -1.0)
        if probability > previous_probability or (
            probability == previous_probability and _quality(row) > _quality(previous)
        ):
            best[match_id] = row
    return sorted(best.values(), key=_quality, reverse=True)


def _suspect_times(rows: list[dict[str, Any]]) -> set[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        raw = str((row.get("match") or {}).get("time") or "").strip()
        if raw:
            counts[raw] += 1
    return {time for time, count in counts.items() if count >= 4}


def _start_minutes(row: dict[str, Any], suspect: set[str]) -> int | None:
    raw = str((row.get("match") or {}).get("time") or "").strip()
    if raw in suspect or len(raw) < 5 or raw[2:3] != ":":
        return None
    try:
        hour, minute = int(raw[:2]), int(raw[3:5])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _build_sequence(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    suspect = _suspect_times(rows)
    confirmed = [row for row in rows if _start_minutes(row, suspect) is not None]
    confirmed.sort(key=lambda row: (_start_minutes(row, suspect) or 0, -_quality(row)))

    n = len(confirmed)
    cap = min(TARGET_GAMES, n)
    previous: list[int] = []
    starts = [_start_minutes(row, suspect) or 0 for row in confirmed]
    for i, start in enumerate(starts):
        j = i - 1
        while j >= 0 and start - starts[j] < MIN_GAP_MINUTES:
            j -= 1
        previous.append(j)

    dp = [[0.0] * (cap + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        weight = _quality(confirmed[i - 1])
        prev_row = previous[i - 1] + 1
        for k in range(1, cap + 1):
            dp[i][k] = max(dp[i - 1][k], weight + dp[prev_row][k - 1])

    best_k = max(range(cap + 1), key=lambda k: dp[n][k]) if cap else 0
    chosen: list[dict[str, Any]] = []
    i, k = n, best_k
    while i > 0 and k > 0:
        weight = _quality(confirmed[i - 1])
        prev_row = previous[i - 1] + 1
        take = weight + dp[prev_row][k - 1]
        if take > dp[i - 1][k] + 1e-9:
            chosen.append(confirmed[i - 1])
            i = prev_row
            k -= 1
        else:
            i -= 1
    chosen.reverse()

    used = {str((row.get("match") or {}).get("match_id")) for row in chosen}
    fill = [row for row in rows if str((row.get("match") or {}).get("match_id")) not in used]
    fill.sort(key=_quality, reverse=True)
    while len(chosen) < TARGET_GAMES and fill:
        chosen.append(fill.pop(0))

    selected = chosen[:TARGET_GAMES]
    selected.sort(
        key=lambda row: (
            0 if _start_minutes(row, suspect) is not None else 1,
            _start_minutes(row, suspect) if _start_minutes(row, suspect) is not None else 9999,
            -_quality(row),
        )
    )
    return selected, suspect


def _snapshot(row: dict[str, Any], position: int, suspect: set[str]) -> dict[str, Any]:
    match = dict(row.get("match") or {})
    raw_time = str(match.get("time") or "").strip()
    time_confirmed = _start_minutes(row, suspect) is not None
    return {
        "position": position,
        "match_id": match.get("match_id"),
        "match": match,
        "selected_player": row.get("selected_player"),
        "opponent": row.get("opponent"),
        "odd": row.get("odd") or (row.get("selected_market") or {}).get("best_odd"),
        "selected_market": row.get("selected_market") or {},
        "final_probability": row.get("final_probability"),
        "confidence": row.get("confidence"),
        "edge_pp": row.get("edge_pp"),
        "data_quality": row.get("data_quality"),
        "disagreement_pp": row.get("disagreement_pp"),
        "signals": row.get("signals") or {},
        "analysis_status": row.get("status"),
        "reject_reasons": list(row.get("reject_reasons", []) or []),
        "scheduled_time_at_freeze": raw_time or None,
        "time_confirmed_at_freeze": time_confirmed,
        "result": {
            "status": "PENDING",
            "winner": None,
            "score": None,
            "resolved_at": None,
        },
    }


def sequence_path(root: Path, target_date: str) -> Path:
    return root / "data" / "sequences" / f"{target_date}.json"


def freeze_sequence(root: Path, board: dict[str, Any]) -> dict[str, Any]:
    """Create the six-game list exactly once for a board date.

    Once the file exists, this function never replaces its selections. Later runs may
    only append results through ``update_sequence_results``.
    """
    target_date = str(board.get("board_date") or board.get("date") or "").strip()
    if not target_date:
        return {"status": "NO_BOARD_DATE", "games": []}
    path = sequence_path(root, target_date)
    if path.exists():
        return _load(path)

    eligible = _best_per_match(board)
    if len(eligible) < TARGET_GAMES:
        return {
            "status": "WAITING_FOR_SIX_ELIGIBLE_GAMES",
            "date": target_date,
            "eligible": len(eligible),
            "games": [],
        }

    selected, suspect = _build_sequence(eligible)
    if len(selected) < TARGET_GAMES:
        return {
            "status": "WAITING_FOR_SIX_ELIGIBLE_GAMES",
            "date": target_date,
            "eligible": len(eligible),
            "games": [],
        }

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "status": "FROZEN",
        "date": target_date,
        "created_at": now,
        "updated_at": now,
        "target_games": TARGET_GAMES,
        "min_probability": MIN_PROBABILITY,
        "min_gap_minutes": MIN_GAP_MINUTES,
        "model_version": board.get("model_version"),
        "source_board_last_run_at": board.get("last_run_at"),
        "games": [_snapshot(row, index, suspect) for index, row in enumerate(selected, 1)],
        "summary": {
            "games": TARGET_GAMES,
            "resolved": 0,
            "hits": 0,
            "misses": 0,
            "accuracy": None,
        },
    }
    write_json(path, payload)
    return payload


def _winner_for_fixture(fixture: Any) -> dict[str, Any] | None:
    winner = str(fixture.winner or "").strip().lower()
    if winner == "first player":
        return {"key": fixture.player_a.key, "name": fixture.player_a.name}
    if winner == "second player":
        return {"key": fixture.player_b.key, "name": fixture.player_b.name}
    return None


def update_sequence_results(root: Path, target_date: str, fixtures: Iterable[Any]) -> dict[str, Any]:
    path = sequence_path(root, target_date)
    if not path.exists():
        return {"status": "NO_SEQUENCE", "date": target_date}

    payload = _load(path)
    by_match = {str(fixture.match_id): fixture for fixture in fixtures}
    changed = False
    for game in payload.get("games", []) or []:
        fixture = by_match.get(str(game.get("match_id") or ""))
        if fixture is None:
            continue
        winner = _winner_for_fixture(fixture)
        if winner is None:
            continue
        selected_key = str((game.get("selected_player") or {}).get("key") or "")
        hit = selected_key == str(winner.get("key") or "")
        next_result = {
            "status": "HIT" if hit else "MISS",
            "winner": winner,
            "score": (fixture.raw or {}).get("event_final_result"),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        current = game.get("result") or {}
        if (
            current.get("status") != next_result["status"]
            or current.get("winner") != next_result["winner"]
            or current.get("score") != next_result["score"]
        ):
            game["result"] = next_result
            changed = True

    games = payload.get("games", []) or []
    resolved = [game for game in games if (game.get("result") or {}).get("status") in {"HIT", "MISS"}]
    hits = sum((game.get("result") or {}).get("status") == "HIT" for game in resolved)
    payload["summary"] = {
        "games": len(games),
        "resolved": len(resolved),
        "hits": hits,
        "misses": len(resolved) - hits,
        "accuracy": (hits / len(resolved)) if resolved else None,
    }
    if changed:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(path, payload)
    return payload
