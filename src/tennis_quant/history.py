from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tennis_quant.storage import write_json


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _market(raw_odds: dict[str, Any]) -> dict[str, Any]:
    home_away = raw_odds.get("Home/Away", {}) if isinstance(raw_odds, dict) else {}
    home = home_away.get("Home", {}) or {}
    away = home_away.get("Away", {}) or {}

    def side(rows: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for book, odd in sorted(rows.items(), key=lambda x: str(x[0]).lower()):
            try:
                value = float(odd)
            except (TypeError, ValueError):
                continue
            out.append({"bookmaker": str(book), "odd": value})
        return out

    home_rows = side(home)
    away_rows = side(away)
    names = sorted({x["bookmaker"] for x in home_rows + away_rows}, key=str.lower)
    return {
        "bookmakers": names,
        "bookmaker_count": len(names),
        "home": home_rows,
        "away": away_rows,
    }


def _result_from_fixture(fixture: Any) -> dict[str, Any]:
    status = str(getattr(fixture, "status", "") or "")
    winner = str(getattr(fixture, "winner", "") or "").strip().lower()
    winner_player = None
    if winner == "first player":
        winner_player = {
            "key": fixture.player_a.key,
            "name": fixture.player_a.name,
        }
    elif winner == "second player":
        winner_player = {
            "key": fixture.player_b.key,
            "name": fixture.player_b.name,
        }
    score = None
    raw = getattr(fixture, "raw", {}) or {}
    score = raw.get("event_final_result")
    finished = status.lower() == "finished" and winner_player is not None
    return {
        "status": "FINISHED" if finished else (status.upper() or "PENDING"),
        "winner": winner_player,
        "score": score,
        "resolved": finished,
        "updated_at": _now(),
    }


def _analysis_row(candidate: Any) -> dict[str, Any]:
    row = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
    selected_market = row.get("selected_market") or {}
    return {
        "selected_player": row.get("selected_player"),
        "opponent": row.get("opponent"),
        "status": row.get("status"),
        "rank": row.get("rank"),
        "odd": selected_market.get("best_odd"),
        "bookmakers": selected_market.get("bookmakers"),
        "bookmaker_odds": selected_market.get("bookmaker_odds", {}),
        "final_probability": row.get("final_probability"),
        "market_probability": row.get("market_probability"),
        "edge_pp": row.get("edge_pp"),
        "confidence": row.get("confidence"),
        "data_quality": row.get("data_quality"),
        "disagreement_pp": row.get("disagreement_pp"),
        "reject_reasons": row.get("reject_reasons", []),
        "signals": row.get("signals", {}),
        "model_version": row.get("model_version"),
    }


def _snapshot_payload(market: dict[str, Any], analyses: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "captured_at": _now(),
        "market": market,
        "analyses": analyses,
    }


def _same_snapshot(a: dict[str, Any] | None, b: dict[str, Any]) -> bool:
    if not a:
        return False
    a_cmp = {k: v for k, v in a.items() if k != "captured_at"}
    b_cmp = {k: v for k, v in b.items() if k != "captured_at"}
    return a_cmp == b_cmp


def _day_paths(root: Path, day: str) -> tuple[Path, Path]:
    return (
        root / "data" / "history" / f"{day}.json",
        root / "dashboard" / "history" / f"{day}.json",
    )


def record_analysis_history(
    root: Path,
    day: str,
    fixtures: Iterable[Any],
    odds_by_match: dict[str, Any],
    ranked_candidates: Iterable[Any],
    model_version: str,
    live_source: str,
) -> dict[str, Any]:
    data_path, dashboard_path = _day_paths(root, day)
    ledger = _load(data_path, {
        "date": day,
        "created_at": _now(),
        "updated_at": _now(),
        "model_versions": [],
        "live_sources": [],
        "games": [],
    })

    if model_version and model_version not in ledger["model_versions"]:
        ledger["model_versions"].append(model_version)
    if live_source and live_source not in ledger["live_sources"]:
        ledger["live_sources"].append(live_source)

    existing = {str(g.get("match_id")): g for g in ledger.get("games", [])}
    by_match: dict[str, list[dict[str, Any]]] = {}
    for candidate in ranked_candidates:
        row = _analysis_row(candidate)
        match = candidate.match if hasattr(candidate, "match") else None
        match_id = str(getattr(match, "match_id", "") or "")
        if match_id:
            by_match.setdefault(match_id, []).append(row)

    for fixture in fixtures:
        if str(getattr(fixture, "event_type", "")).lower() != "atp singles":
            continue
        match_id = str(fixture.match_id)
        market = _market(odds_by_match.get(match_id, {}))
        analyses = by_match.get(match_id, [])
        analyses.sort(key=lambda x: (x.get("rank") is None, x.get("rank") or 9999, str((x.get("selected_player") or {}).get("name", ""))))

        game = existing.get(match_id)
        if game is None:
            game = {
                "match_id": match_id,
                "date": fixture.date,
                "time": fixture.time,
                "tournament": fixture.tournament,
                "surface": fixture.surface,
                "event_type": fixture.event_type,
                "player_a": {"key": fixture.player_a.key, "name": fixture.player_a.name},
                "player_b": {"key": fixture.player_b.key, "name": fixture.player_b.name},
                "first_seen_at": _now(),
                "last_seen_at": _now(),
                "market": market,
                "analyses": analyses,
                "snapshots": [],
                "result": _result_from_fixture(fixture),
            }
            existing[match_id] = game
        else:
            game["last_seen_at"] = _now()
            game["time"] = fixture.time or game.get("time")
            game["surface"] = fixture.surface or game.get("surface")
            if market.get("bookmaker_count"):
                game["market"] = market
            if analyses:
                game["analyses"] = analyses
            result = _result_from_fixture(fixture)
            if result.get("resolved") or not (game.get("result") or {}).get("resolved"):
                game["result"] = result

        snapshot = _snapshot_payload(game.get("market", market), game.get("analyses", analyses))
        snapshots = game.setdefault("snapshots", [])
        if not _same_snapshot(snapshots[-1] if snapshots else None, snapshot):
            snapshots.append(snapshot)

    ledger["updated_at"] = _now()
    ledger["games"] = sorted(existing.values(), key=lambda g: (g.get("time") or "99:99", g.get("tournament") or "", g.get("match_id") or ""))
    ledger["summary"] = summarize_day(ledger)
    write_json(data_path, ledger)
    write_json(dashboard_path, ledger)
    rebuild_history_index(root)
    return ledger


def update_history_results(root: Path, day: str, fixtures: Iterable[Any]) -> None:
    data_path, dashboard_path = _day_paths(root, day)
    if not data_path.exists():
        return
    ledger = _load(data_path, {})
    if not ledger:
        return
    games = {str(g.get("match_id")): g for g in ledger.get("games", [])}
    changed = False
    for fixture in fixtures:
        game = games.get(str(fixture.match_id))
        if not game:
            continue
        result = _result_from_fixture(fixture)
        current = game.get("result") or {}
        if result.get("resolved") and result != current:
            game["result"] = result
            changed = True
    if changed:
        ledger["updated_at"] = _now()
        ledger["games"] = list(games.values())
        ledger["summary"] = summarize_day(ledger)
        write_json(data_path, ledger)
        write_json(dashboard_path, ledger)
        rebuild_history_index(root)


def summarize_day(ledger: dict[str, Any]) -> dict[str, Any]:
    games = ledger.get("games", []) or []
    approved = 0
    resolved_approved = 0
    wins = 0
    losses = 0
    bookmaker_names: set[str] = set()
    for game in games:
        bookmaker_names.update((game.get("market") or {}).get("bookmakers", []) or [])
        result = game.get("result") or {}
        winner_key = ((result.get("winner") or {}).get("key"))
        for analysis in game.get("analyses", []) or []:
            if analysis.get("status") != "APPROVED":
                continue
            approved += 1
            if result.get("resolved"):
                resolved_approved += 1
                selected_key = ((analysis.get("selected_player") or {}).get("key"))
                if selected_key and winner_key and selected_key == winner_key:
                    wins += 1
                else:
                    losses += 1
    return {
        "games": len(games),
        "approved": approved,
        "resolved_approved": resolved_approved,
        "wins": wins,
        "losses": losses,
        "accuracy": (wins / resolved_approved) if resolved_approved else None,
        "bookmakers": sorted(bookmaker_names, key=str.lower),
        "bookmaker_count": len(bookmaker_names),
    }


def rebuild_history_index(root: Path) -> dict[str, Any]:
    history_root = root / "data" / "history"
    dates: list[dict[str, Any]] = []
    if history_root.exists():
        for path in sorted(history_root.glob("????-??-??.json"), reverse=True):
            ledger = _load(path, {})
            if not ledger:
                continue
            dates.append({
                "date": ledger.get("date") or path.stem,
                "updated_at": ledger.get("updated_at"),
                "summary": ledger.get("summary") or summarize_day(ledger),
            })
    index = {"updated_at": _now(), "dates": dates}
    write_json(root / "dashboard" / "history" / "index.json", index)
    return index
