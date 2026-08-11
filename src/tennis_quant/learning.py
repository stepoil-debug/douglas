from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tennis_quant.failure import classify_postmortem
from tennis_quant.storage import write_json


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _winner_key(fixture: Any) -> str | None:
    winner = str(getattr(fixture, "winner", "") or "").strip().lower()
    if winner == "first player":
        return fixture.player_a.key
    if winner == "second player":
        return fixture.player_b.key
    return None


def record_learning_board(
    root: Path,
    target_date: str,
    candidates: list[dict[str, Any]],
    model_version: str,
    source: str,
) -> dict[str, Any]:
    """Persist one model pick per match. Re-runs update the provisional D+1 board until match day."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        match_id = str((row.get("match") or {}).get("match_id") or "")
        if match_id:
            grouped[match_id].append(row)

    picks: list[dict[str, Any]] = []
    for match_id, rows in grouped.items():
        # The model's actual directional opinion for learning is the side with the
        # highest predicted win probability, regardless of whether it was approved.
        pick = max(rows, key=lambda r: float(r.get("final_probability") or 0.0))
        match = pick.get("match") or {}
        selected = pick.get("selected_player") or {}
        opponent = pick.get("opponent") or {}
        market = pick.get("selected_market") or {}
        picks.append({
            "match_id": match_id,
            "date": target_date,
            "tournament": match.get("tournament"),
            "time": match.get("time"),
            "surface": match.get("surface"),
            "predicted_player": selected,
            "opponent": opponent,
            "decision": pick.get("status"),
            "rank": pick.get("rank"),
            "odd": market.get("best_odd"),
            "bookmakers": market.get("bookmakers"),
            "final_probability": pick.get("final_probability"),
            "confidence": pick.get("confidence"),
            "edge_pp": pick.get("edge_pp"),
            "data_quality": pick.get("data_quality"),
            "disagreement_pp": pick.get("disagreement_pp"),
            "signals": pick.get("signals") or {},
            "reject_reasons": pick.get("reject_reasons") or [],
            "result": {"status": "PENDING", "hit": None, "winner": None, "score": None},
        })

    picks.sort(key=lambda r: (
        0 if r.get("decision") == "APPROVED" else 1 if r.get("decision") == "SHADOW" else 2,
        r.get("rank") or 999999,
        -(float(r.get("confidence") or 0)),
    ))
    payload = {
        "date": target_date,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model_version": model_version,
        "source": source,
        "status": "PROVISIONAL_D1",
        "matches": picks,
    }
    write_json(root / "data" / "learning" / f"{target_date}.json", payload)
    return payload


def reconcile_learning_results(root: Path, target_date: str, fixtures: Iterable[Any]) -> dict[str, Any] | None:
    path = root / "data" / "learning" / f"{target_date}.json"
    if not path.exists():
        return None
    payload = _load(path, {})
    fixture_map = {str(f.match_id): f for f in fixtures}
    changed = False
    for row in payload.get("matches", []) or []:
        fixture = fixture_map.get(str(row.get("match_id")))
        if not fixture:
            continue
        winner_key = _winner_key(fixture)
        if not winner_key:
            continue
        selected_key = str((row.get("predicted_player") or {}).get("key") or "")
        hit = bool(selected_key and selected_key == winner_key)
        winner_name = fixture.player_a.name if winner_key == fixture.player_a.key else fixture.player_b.name
        result = {
            "status": "HIT" if hit else "MISS",
            "hit": hit,
            "winner": {"key": winner_key, "name": winner_name},
            "score": (fixture.raw or {}).get("event_final_result"),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        if not hit:
            result["postmortem"] = classify_postmortem(row)
        row["result"] = result
        changed = True
    if changed:
        payload["status"] = "RESULTS_UPDATING"
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(path, payload)
    return payload


def _bucket(value: float | None, cuts: list[tuple[float, str]]) -> str:
    if value is None:
        return "N/A"
    for limit, label in cuts:
        if value < limit:
            return label
    return cuts[-1][1]


def aggregate_knowledge(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "data" / "learning").glob("????-??-??.json")):
        payload = _load(path, {})
        for row in payload.get("matches", []) or []:
            result = row.get("result") or {}
            if result.get("status") in {"HIT", "MISS"}:
                rows.append(row)

    def stat(sample: list[dict[str, Any]]) -> dict[str, Any]:
        hits = sum(1 for r in sample if (r.get("result") or {}).get("hit") is True)
        return {"n": len(sample), "hits": hits, "misses": len(sample) - hits, "accuracy": (hits / len(sample)) if sample else None}

    by_decision: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_probability: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_confidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failures: dict[str, int] = defaultdict(int)
    for row in rows:
        by_decision[str(row.get("decision") or "UNKNOWN")].append(row)
        p = float(row.get("final_probability") or 0)
        c = float(row.get("confidence") or 0)
        by_probability[_bucket(p, [(0.55, "<55%"), (0.60, "55-60%"), (0.65, "60-65%"), (0.70, "65-70%"), (0.75, "70-75%"), (9, "75%+")])].append(row)
        by_confidence[_bucket(c, [(50, "<50"), (60, "50-60"), (70, "60-70"), (80, "70-80"), (90, "80-90"), (999, "90+")])].append(row)
        if (row.get("result") or {}).get("status") == "MISS":
            for tag in (((row.get("result") or {}).get("postmortem") or {}).get("tags") or []):
                failures[str(tag)] += 1

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "overall": stat(rows),
        "by_decision": {k: stat(v) for k, v in sorted(by_decision.items())},
        "by_probability": {k: stat(v) for k, v in by_probability.items()},
        "by_confidence": {k: stat(v) for k, v in by_confidence.items()},
        "failure_tags": dict(sorted(failures.items(), key=lambda kv: kv[1], reverse=True)),
        "last_100": stat(rows[-100:]),
        "last_500": stat(rows[-500:]),
    }
    write_json(root / "data" / "learning" / "knowledge.json", output)
    write_json(root / "dashboard" / "learning.json", output)
    return output
