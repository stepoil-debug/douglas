from __future__ import annotations

from typing import Any


def _winner_matches_player(match: dict[str, Any], player_key: str) -> bool | None:
    winner = str(match.get("event_winner", "")).strip().lower()
    first = str(match.get("first_player_key", ""))
    second = str(match.get("second_player_key", ""))
    if winner in {"first player", "first_player", "1", "home"}:
        return player_key == first
    if winner in {"second player", "second_player", "2", "away"}:
        return player_key == second
    return None


def recent_win_rate(matches: list[dict[str, Any]], player_key: str, limit: int = 10) -> tuple[float, int]:
    seen = wins = 0
    for match in matches[:limit]:
        result = _winner_matches_player(match, player_key)
        if result is None:
            continue
        seen += 1
        wins += int(result)
    return ((wins / seen) if seen else 0.5), seen


def h2h_rate(matches: list[dict[str, Any]], player_key: str, limit: int = 10) -> tuple[float, int]:
    return recent_win_rate(matches, player_key, limit=limit)
