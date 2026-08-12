from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tennis_quant.failure import classify_postmortem
from tennis_quant.history import update_history_results
from tennis_quant.learning import backfill_learning_from_history, reconcile_learning_results
from tennis_quant.public_results import finished_fixtures
from tennis_quant.ratings import RatingStore, margin_k
from tennis_quant.sequence import update_sequence_results
from tennis_quant.storage import write_json


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _selected_won(snapshot: dict[str, Any], fixture: Any) -> bool | None:
    winner = str(fixture.winner or "").strip().lower()
    selected = str(snapshot["selected_player"]["key"])
    if winner == "first player":
        return selected == fixture.player_a.key
    if winner == "second player":
        return selected == fixture.player_b.key
    return None


def _winner_player(fixture: Any) -> dict[str, Any] | None:
    winner = str(fixture.winner or "").strip().lower()
    if winner == "first player":
        return {"key": fixture.player_a.key, "name": fixture.player_a.name}
    if winner == "second player":
        return {"key": fixture.player_b.key, "name": fixture.player_b.name}
    return None


def _quality_label(snapshot: dict[str, Any], won: bool) -> str:
    strong = (
        float(snapshot.get("edge_pp", 0)) >= 5.0
        and float(snapshot.get("disagreement_pp", 99)) < 10.0
        and float(snapshot.get("data_quality", 0)) >= 0.70
    )
    if won:
        return "GOOD_WIN" if strong else "LUCKY_WIN"
    return "GOOD_LOSS" if strong else "BAD_LOSS"


def reconcile_results(provider, root: Path, target_day: date) -> list[dict[str, Any]]:
    fixtures = {m.match_id: m for m in finished_fixtures(provider, root, target_day)}
    update_history_results(root, target_day.isoformat(), fixtures.values())
    update_sequence_results(root, target_day.isoformat(), fixtures.values())

    # Older boards can predate the dedicated learning ledger. Recover the model's
    # directional opinion strictly from the saved pre-match history before applying
    # results, so yesterday remains auditable without recomputing a prediction.
    backfill_learning_from_history(root, target_day.isoformat())
    reconcile_learning_results(root, target_day.isoformat(), fixtures.values())

    # Ratings learn from every finished result, independently of whether there was
    # an approved betting snapshot for that match.
    ratings = RatingStore(root / "data" / "state" / "ratings.json")
    ratings_changed = False
    for fixture in fixtures.values():
        winner = str(fixture.winner or "").strip().lower()
        k = margin_k(fixture.raw.get("event_final_result"))
        if winner == "first player":
            ratings_changed |= ratings.record_match(fixture.match_id, fixture.player_a.key, fixture.player_b.key, fixture.surface, k=k)
        elif winner == "second player":
            ratings_changed |= ratings.record_match(fixture.match_id, fixture.player_b.key, fixture.player_a.key, fixture.surface, k=k)
    if ratings_changed:
        ratings.save()

    prediction_dir = root / "data" / "predictions" / target_day.isoformat()
    if not prediction_dir.exists():
        return []

    output: list[dict[str, Any]] = []
    for snapshot_path in sorted(prediction_dir.glob("*.json")):
        snapshot = _load(snapshot_path)
        match_id = str(snapshot["match"]["match_id"])
        fixture = fixtures.get(match_id)
        if not fixture:
            continue
        won = _selected_won(snapshot, fixture)
        if won is None:
            continue

        label = _quality_label(snapshot, won)
        postmortem = classify_postmortem(snapshot) if not won else {"tags": [], "evidence": [], "status": "NOT_REQUIRED"}
        result = {
            "date": target_day.isoformat(),
            "match_id": match_id,
            "selected_player": snapshot["selected_player"],
            "opponent": snapshot["opponent"],
            "selection_status": snapshot.get("status"),
            "rank": snapshot.get("rank"),
            "odd": snapshot.get("selected_market", {}).get("best_odd"),
            "bookmakers": snapshot.get("selected_market", {}).get("bookmakers"),
            "final_probability": snapshot.get("final_probability"),
            "confidence": snapshot.get("confidence"),
            "won": won,
            "winner": _winner_player(fixture),
            "score": (fixture.raw or {}).get("event_final_result"),
            "quality_label": label,
            "model_version": snapshot.get("model_version"),
            "postmortem": postmortem,
        }
        write_json(root / "data" / "results" / target_day.isoformat() / snapshot_path.name, result)
        output.append(result)
    return output


def reconcile_recent(provider, root: Path, today: date, days_back: int = 3) -> list[dict[str, Any]]:
    all_results: list[dict[str, Any]] = []
    for offset in range(days_back + 1):
        target = today - timedelta(days=offset)
        try:
            all_results.extend(reconcile_results(provider, root, target))
        except Exception:
            continue
    return all_results


def aggregate_metrics(root: Path) -> dict[str, Any]:
    results_root = root / "data" / "results"
    rows: list[dict[str, Any]] = []
    if results_root.exists():
        for path in results_root.glob("*/*.json"):
            rows.append(_load(path))
    approved = [r for r in rows if r.get("selection_status") == "APPROVED"]
    approved.sort(key=lambda r: (r.get("date", ""), r.get("rank") or 9999), reverse=True)

    def window(n: int) -> dict[str, Any]:
        sample = approved[:n]
        wins = sum(bool(r.get("won")) for r in sample)
        return {"n": len(sample), "wins": wins, "accuracy": (wins / len(sample)) if sample else None}

    labels: dict[str, int] = {}
    for row in approved:
        labels[row["quality_label"]] = labels.get(row["quality_label"], 0) + 1
    return {
        "total_approved_resolved": len(approved),
        "last_10": window(10),
        "last_50": window(50),
        "last_100": window(100),
        "last_500": window(500),
        "quality_labels": labels,
    }
