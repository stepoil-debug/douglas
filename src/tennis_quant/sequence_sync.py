from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tennis_quant.storage import write_json


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _sequence_paths(root: Path) -> list[Path]:
    folder = root / "data" / "sequences"
    if not folder.exists():
        return []
    return sorted(folder.glob("????-??-??.json"))


def _winner_for_fixture(fixture: Any) -> dict[str, Any] | None:
    winner = str(getattr(fixture, "winner", "") or "").strip().lower()
    if winner == "first player":
        return {"key": fixture.player_a.key, "name": fixture.player_a.name}
    if winner == "second player":
        return {"key": fixture.player_b.key, "name": fixture.player_b.name}
    return None


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    games = payload.get("games", []) or []
    resolved = [g for g in games if (g.get("result") or {}).get("status") in {"HIT", "MISS"}]
    hits = sum((g.get("result") or {}).get("status") == "HIT" for g in resolved)
    confirmed = sum(bool(g.get("scheduled_date_current") and g.get("scheduled_time_current")) for g in games)
    return {
        "games": len(games),
        "resolved": len(resolved),
        "hits": hits,
        "misses": len(resolved) - hits,
        "accuracy": (hits / len(resolved)) if resolved else None,
        "schedule_confirmed": confirmed,
    }


def update_all_sequence_schedules(root: Path, fixtures: Iterable[Any]) -> dict[str, Any]:
    """Append verified current date/time to frozen picks without changing the picks.

    A sequence is immutable with respect to player, position, model scores and odds.
    Schedule metadata is allowed to be appended/corrected because a public order of
    play can be published after the pre-match list was frozen or a match can move to
    the following day.
    """
    by_match = {str(getattr(f, "match_id", "")): f for f in fixtures if getattr(f, "match_id", None)}
    changed_files = 0
    matched_games = 0
    now = datetime.now(timezone.utc).isoformat()

    for path in _sequence_paths(root):
        payload = _load(path)
        changed = False
        for game in payload.get("games", []) or []:
            fixture = by_match.get(str(game.get("match_id") or ""))
            if fixture is None:
                continue
            current_date = str(getattr(fixture, "date", "") or "").strip() or None
            current_time = str(getattr(fixture, "time", "") or "").strip() or None
            if not current_date or not current_time:
                continue
            matched_games += 1
            source = str((getattr(fixture, "raw", {}) or {}).get("source") or "public schedule")
            next_values = {
                "scheduled_date_current": current_date,
                "scheduled_time_current": current_time,
                "schedule_verified_at": now,
                "schedule_source": source,
            }
            if any(game.get(key) != value for key, value in next_values.items()):
                game.update(next_values)
                frozen_date = str((game.get("match") or {}).get("date") or payload.get("date") or "")
                frozen_time = str(game.get("scheduled_time_at_freeze") or "")
                game["schedule_changed_from_freeze"] = (
                    bool(frozen_date and current_date != frozen_date)
                    or bool(frozen_time and current_time != frozen_time)
                    or not bool(frozen_time)
                )
                changed = True
        if changed:
            payload["summary"] = _summary(payload)
            payload["updated_at"] = now
            write_json(path, payload)
            changed_files += 1

    return {"status": "OK", "matched_games": matched_games, "changed_files": changed_files}


def update_all_sequence_results(root: Path, fixtures: Iterable[Any]) -> dict[str, Any]:
    """Reconcile finished fixtures against every frozen sequence by stable match id.

    This deliberately scans all sequence dates. A match frozen for D+1 may later be
    rescheduled to D+2; its result still belongs to the original immutable sequence.
    """
    by_match = {str(getattr(f, "match_id", "")): f for f in fixtures if getattr(f, "match_id", None)}
    changed_files = 0
    resolved_games = 0
    now = datetime.now(timezone.utc).isoformat()

    for path in _sequence_paths(root):
        payload = _load(path)
        changed = False
        for game in payload.get("games", []) or []:
            fixture = by_match.get(str(game.get("match_id") or ""))
            if fixture is None:
                continue
            winner = _winner_for_fixture(fixture)
            if winner is None:
                continue
            selected_key = str((game.get("selected_player") or {}).get("key") or "")
            status = "HIT" if selected_key == str(winner.get("key") or "") else "MISS"
            next_result = {
                "status": status,
                "winner": winner,
                "score": (getattr(fixture, "raw", {}) or {}).get("event_final_result"),
                "resolved_at": now,
                "actual_date": str(getattr(fixture, "date", "") or "") or None,
                "actual_time": str(getattr(fixture, "time", "") or "") or None,
            }
            current = game.get("result") or {}
            comparable = ("status", "winner", "score", "actual_date", "actual_time")
            if any(current.get(key) != next_result.get(key) for key in comparable):
                game["result"] = next_result
                changed = True
                resolved_games += 1
        if changed:
            payload["summary"] = _summary(payload)
            payload["updated_at"] = now
            write_json(path, payload)
            changed_files += 1

    return {"status": "OK", "resolved_games": resolved_games, "changed_files": changed_files}
