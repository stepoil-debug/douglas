from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timezone
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


def _norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _pair_key(first: Any, second: Any) -> tuple[str, str] | None:
    a, b = _norm_name(first), _norm_name(second)
    if not a or not b:
        return None
    return tuple(sorted((a, b)))


def _fixture_pair(fixture: Any) -> tuple[str, str] | None:
    a = getattr(getattr(fixture, "player_a", None), "name", None) or getattr(fixture, "player_a_name", None)
    b = getattr(getattr(fixture, "player_b", None), "name", None) or getattr(fixture, "player_b_name", None)
    return _pair_key(a, b)


def _game_pair(game: dict[str, Any]) -> tuple[str, str] | None:
    match = game.get("match") or {}
    a = (match.get("player_a") or {}).get("name")
    b = (match.get("player_b") or {}).get("name")
    if not a or not b:
        a = (game.get("selected_player") or {}).get("name")
        b = (game.get("opponent") or {}).get("name")
    return _pair_key(a, b)


def _fixture_date(fixture: Any) -> date | None:
    raw = str(getattr(fixture, "date", "") or "").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _find_fixture(
    game: dict[str, Any],
    sequence_date: str,
    by_match: dict[str, Any],
    by_pair: dict[tuple[str, str], list[Any]],
) -> tuple[Any | None, str | None]:
    exact = by_match.get(str(game.get("match_id") or ""))
    if exact is not None:
        return exact, "MATCH_ID"

    pair = _game_pair(game)
    candidates = list(by_pair.get(pair, [])) if pair else []
    if not candidates:
        return None, None
    try:
        origin = date.fromisoformat(sequence_date)
    except ValueError:
        origin = None
    if origin:
        close = [f for f in candidates if _fixture_date(f) and abs((_fixture_date(f) - origin).days) <= 3]
        if close:
            candidates = close
        else:
            return None, None
    candidates.sort(key=lambda f: abs(((_fixture_date(f) or origin) - origin).days) if origin else 0)
    return candidates[0], "PLAYER_PAIR"


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


def _indexes(fixtures: Iterable[Any]) -> tuple[dict[str, Any], dict[tuple[str, str], list[Any]]]:
    rows = list(fixtures)
    by_match = {str(getattr(f, "match_id", "")): f for f in rows if getattr(f, "match_id", None)}
    by_pair: dict[tuple[str, str], list[Any]] = {}
    for fixture in rows:
        pair = _fixture_pair(fixture)
        if pair:
            by_pair.setdefault(pair, []).append(fixture)
    return by_match, by_pair


def update_all_sequence_schedules(root: Path, fixtures: Iterable[Any]) -> dict[str, Any]:
    """Append verified current date/time without changing any frozen prediction."""
    by_match, by_pair = _indexes(fixtures)
    changed_files = 0
    matched_games = 0
    id_matches = 0
    pair_matches = 0
    now = datetime.now(timezone.utc).isoformat()

    for path in _sequence_paths(root):
        payload = _load(path)
        sequence_date = str(payload.get("date") or path.stem)
        changed = False
        for game in payload.get("games", []) or []:
            fixture, match_method = _find_fixture(game, sequence_date, by_match, by_pair)
            if fixture is None:
                continue
            current_date = str(getattr(fixture, "date", "") or "").strip() or None
            current_time = str(getattr(fixture, "time", "") or "").strip() or None
            if not current_date or not current_time:
                continue
            matched_games += 1
            id_matches += match_method == "MATCH_ID"
            pair_matches += match_method == "PLAYER_PAIR"
            source = str((getattr(fixture, "raw", {}) or {}).get("source") or "public schedule")
            next_values = {
                "scheduled_date_current": current_date,
                "scheduled_time_current": current_time,
                "schedule_verified_at": now,
                "schedule_source": source,
                "schedule_match_method": match_method,
            }
            if any(game.get(key) != value for key, value in next_values.items()):
                game.update(next_values)
                frozen_date = str((game.get("match") or {}).get("date") or sequence_date)
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

    return {
        "status": "OK",
        "matched_games": matched_games,
        "match_id_matches": id_matches,
        "player_pair_matches": pair_matches,
        "changed_files": changed_files,
    }


def update_all_sequence_results(root: Path, fixtures: Iterable[Any]) -> dict[str, Any]:
    """Append finished results to the original frozen list, even after rescheduling."""
    by_match, by_pair = _indexes(fixtures)
    changed_files = 0
    resolved_games = 0
    pair_matches = 0
    now = datetime.now(timezone.utc).isoformat()

    for path in _sequence_paths(root):
        payload = _load(path)
        sequence_date = str(payload.get("date") or path.stem)
        changed = False
        for game in payload.get("games", []) or []:
            fixture, match_method = _find_fixture(game, sequence_date, by_match, by_pair)
            if fixture is None:
                continue
            winner = _winner_for_fixture(fixture)
            if winner is None:
                continue
            selected = game.get("selected_player") or {}
            selected_key = str(selected.get("key") or "")
            won = selected_key and selected_key == str(winner.get("key") or "")
            if not won and _norm_name(selected.get("name")) == _norm_name(winner.get("name")):
                won = True
            status = "HIT" if won else "MISS"
            next_result = {
                "status": status,
                "winner": winner,
                "score": (getattr(fixture, "raw", {}) or {}).get("event_final_result"),
                "resolved_at": now,
                "actual_date": str(getattr(fixture, "date", "") or "") or None,
                "actual_time": str(getattr(fixture, "time", "") or "") or None,
                "match_method": match_method,
            }
            current = game.get("result") or {}
            comparable = ("status", "winner", "score", "actual_date", "actual_time", "match_method")
            if any(current.get(key) != next_result.get(key) for key in comparable):
                game["result"] = next_result
                changed = True
                resolved_games += 1
                pair_matches += match_method == "PLAYER_PAIR"
        if changed:
            payload["summary"] = _summary(payload)
            payload["updated_at"] = now
            write_json(path, payload)
            changed_files += 1

    return {
        "status": "OK",
        "resolved_games": resolved_games,
        "player_pair_matches": pair_matches,
        "changed_files": changed_files,
    }
