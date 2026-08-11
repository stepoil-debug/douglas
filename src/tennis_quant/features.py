from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Iterable


def clamp(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, value))


def _winner_matches_player(match: dict[str, Any], player_key: str) -> bool | None:
    winner = str(match.get("event_winner", "")).strip().lower()
    first = str(match.get("first_player_key", ""))
    second = str(match.get("second_player_key", ""))
    if winner in {"first player", "first_player", "1", "home"}:
        return player_key == first
    if winner in {"second player", "second_player", "2", "away"}:
        return player_key == second
    return None


def _sets_for_player(match: dict[str, Any], player_key: str) -> tuple[int, int] | None:
    raw = str(match.get("event_final_result", ""))
    try:
        left, right = [int(x.strip()) for x in raw.split("-")[:2]]
    except (ValueError, TypeError):
        return None
    if str(match.get("first_player_key", "")) == player_key:
        return left, right
    if str(match.get("second_player_key", "")) == player_key:
        return right, left
    return None


def recent_win_rate(matches: list[dict[str, Any]], player_key: str, limit: int = 10) -> tuple[float, int]:
    seen = wins = 0
    weighted_wins = 0.0
    total_weight = 0.0
    for idx, match in enumerate(matches[:limit]):
        result = _winner_matches_player(match, player_key)
        if result is None:
            continue
        weight = 0.88 ** idx
        seen += 1
        wins += int(result)
        weighted_wins += weight * int(result)
        total_weight += weight
    # Beta-style shrinkage avoids 100%/0% from tiny samples.
    if not seen or not total_weight:
        return 0.5, 0
    effective = weighted_wins / total_weight
    shrink = min(1.0, seen / 8.0)
    return 0.5 + (effective - 0.5) * shrink, seen


def set_dominance(matches: list[dict[str, Any]], player_key: str, limit: int = 10) -> tuple[float, int]:
    won = lost = seen = 0
    for match in matches[:limit]:
        sets = _sets_for_player(match, player_key)
        if sets is None:
            continue
        w, l = sets
        won += w
        lost += l
        seen += 1
    if not seen or won + lost == 0:
        return 0.5, 0
    raw = (won + 2.0) / (won + lost + 4.0)
    return clamp(raw, 0.20, 0.80), seen


def combined_recent_strength(matches: list[dict[str, Any]], player_key: str, limit: int = 10) -> tuple[float, int]:
    win_rate, seen = recent_win_rate(matches, player_key, limit)
    sets, set_seen = set_dominance(matches, player_key, limit)
    if not set_seen:
        return win_rate, seen
    return 0.72 * win_rate + 0.28 * sets, seen


def h2h_rate(matches: list[dict[str, Any]], player_key: str, limit: int = 8) -> tuple[float, int]:
    rate, seen = recent_win_rate(matches, player_key, limit=limit)
    # H2H remains deliberately conservative.
    return 0.5 + (rate - 0.5) * min(0.55, seen / 10.0), seen


def pair_probability(strength_a: float, strength_b: float, scale: float = 1.0) -> float:
    delta = (strength_a - strength_b) * scale
    return clamp(0.5 + delta, 0.20, 0.80)


def ranking_probability(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float | None:
    if not a or not b:
        return None
    try:
        pa = float(a.get("points") or 0)
        pb = float(b.get("points") or 0)
    except (TypeError, ValueError):
        pa = pb = 0
    if pa > 0 and pb > 0:
        # ATP points are useful but capped so ranking can never dominate the ensemble.
        return clamp(pa / (pa + pb), 0.28, 0.72)
    try:
        ra = max(1.0, float(a.get("place")))
        rb = max(1.0, float(b.get("place")))
    except (TypeError, ValueError):
        return None
    sa, sb = ra ** -0.55, rb ** -0.55
    return clamp(sa / (sa + sb), 0.28, 0.72)


def _season_stats(profile: dict[str, Any], target_year: int) -> dict[str, Any] | None:
    rows = profile.get("stats", []) if isinstance(profile, dict) else []
    singles: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("type", "")).lower() != "singles":
            continue
        singles.append(row)
    if not singles:
        return None
    singles.sort(key=lambda x: abs(int(str(x.get("season", target_year))) - target_year) if str(x.get("season", "")).isdigit() else 999)
    return singles[0]


def _wl_strength(won: Any, lost: Any) -> tuple[float, int]:
    try:
        w = int(won or 0)
        l = int(lost or 0)
    except (TypeError, ValueError):
        return 0.5, 0
    n = w + l
    if n <= 0:
        return 0.5, 0
    return (w + 3.0) / (n + 6.0), n


def profile_strength(profile: dict[str, Any], target_year: int, surface: str | None) -> tuple[float, int]:
    row = _season_stats(profile, target_year)
    if not row:
        return 0.5, 0
    surface_key = str(surface or "").strip().lower()
    if "hard" in surface_key:
        s, n = _wl_strength(row.get("hard_won"), row.get("hard_lost"))
        if n:
            return s, n
    if "clay" in surface_key:
        s, n = _wl_strength(row.get("clay_won"), row.get("clay_lost"))
        if n:
            return s, n
    if "grass" in surface_key:
        s, n = _wl_strength(row.get("grass_won"), row.get("grass_lost"))
        if n:
            return s, n
    return _wl_strength(row.get("matches_won"), row.get("matches_lost"))


def _parse_event_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fatigue_readiness(matches: list[dict[str, Any]], target_date: date, limit: int = 12) -> tuple[float, dict[str, int | None]]:
    dates = [_parse_event_date(m.get("event_date")) for m in matches[:limit]]
    dates = [d for d in dates if d and d < target_date]
    if not dates:
        return 0.65, {"last_1d": 0, "last_3d": 0, "last_7d": 0, "days_rest": None}
    gaps = [(target_date - d).days for d in dates]
    last_1 = sum(g <= 1 for g in gaps)
    last_3 = sum(g <= 3 for g in gaps)
    last_7 = sum(g <= 7 for g in gaps)
    days_rest = min(gaps)
    penalty = 0.13 * last_1 + 0.055 * max(0, last_3 - last_1) + 0.018 * max(0, last_7 - last_3)
    readiness = clamp(0.78 - penalty + min(days_rest, 5) * 0.018, 0.28, 0.88)
    return readiness, {"last_1d": last_1, "last_3d": last_3, "last_7d": last_7, "days_rest": days_rest}


def _stat_fraction(stat: dict[str, Any]) -> float | None:
    try:
        won = float(stat.get("stat_won"))
        total = float(stat.get("stat_total"))
        if total > 0:
            return clamp(won / total, 0.0, 1.0)
    except (TypeError, ValueError):
        pass
    raw = str(stat.get("stat_value", "")).strip().replace("%", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    if value > 1:
        value /= 100.0
    return clamp(value, 0.0, 1.0)


def serve_strength(history: Iterable[Any], player_key: str, limit: int = 10) -> tuple[float | None, int]:
    names = {
        "1st serve points won": 0.38,
        "first serve points won": 0.38,
        "2nd serve points won": 0.38,
        "second serve points won": 0.38,
        "break points saved": 0.14,
        "service points won": 0.10,
    }
    total = weighted = 0.0
    matches_seen = 0
    for match in list(history)[:limit]:
        raw = getattr(match, "raw", match if isinstance(match, dict) else {})
        stats = raw.get("statistics", []) if isinstance(raw, dict) else []
        found = False
        for stat in stats or []:
            if not isinstance(stat, dict) or str(stat.get("player_key", "")) != str(player_key):
                continue
            name = str(stat.get("stat_name", "")).strip().lower()
            weight = names.get(name)
            if not weight:
                continue
            value = _stat_fraction(stat)
            if value is None:
                continue
            weighted += value * weight
            total += weight
            found = True
        matches_seen += int(found)
    if total <= 0:
        return None, 0
    return clamp(weighted / total, 0.25, 0.80), matches_seen
