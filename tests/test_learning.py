from pathlib import Path
from types import SimpleNamespace

from tennis_quant.learning import aggregate_knowledge, record_learning_board, reconcile_learning_results


def _candidate(match_id: str, player: str, opponent: str, probability: float, status: str, rank=None):
    return {
        "match": {"match_id": match_id, "tournament": "ATP Test", "time": "14:00", "surface": "Hard"},
        "selected_player": {"key": player, "name": player.upper()},
        "opponent": {"key": opponent, "name": opponent.upper()},
        "selected_market": {"best_odd": 1.70, "bookmakers": 4},
        "signals": {"market": .61, "elo": probability},
        "final_probability": probability,
        "confidence": 82.0 if status == "APPROVED" else 58.0,
        "edge_pp": 5.0,
        "data_quality": .88,
        "disagreement_pp": 5.0,
        "status": status,
        "rank": rank,
        "reject_reasons": [] if status == "APPROVED" else ["CONFIDENCE_TOO_LOW"],
    }


def test_learning_uses_one_directional_pick_per_match(tmp_path: Path):
    board = record_learning_board(tmp_path, "2026-08-12", [
        _candidate("m1", "a", "b", .72, "APPROVED", 1),
        _candidate("m1", "b", "a", .28, "REJECTED"),
    ], "v1", "source")
    assert len(board["matches"]) == 1
    assert board["matches"][0]["predicted_player"]["key"] == "a"
    assert board["matches"][0]["result"]["status"] == "PENDING"


def test_learning_reconciles_hit_and_builds_knowledge(tmp_path: Path):
    record_learning_board(tmp_path, "2026-08-12", [
        _candidate("m1", "a", "b", .72, "APPROVED", 1),
        _candidate("m1", "b", "a", .28, "REJECTED"),
    ], "v1", "source")
    fixture = SimpleNamespace(
        match_id="m1",
        winner="First Player",
        player_a=SimpleNamespace(key="a", name="A"),
        player_b=SimpleNamespace(key="b", name="B"),
        raw={"event_final_result": "2 - 0"},
    )
    out = reconcile_learning_results(tmp_path, "2026-08-12", [fixture])
    assert out["matches"][0]["result"]["status"] == "HIT"
    k = aggregate_knowledge(tmp_path)
    assert k["overall"]["n"] == 1
    assert k["overall"]["hits"] == 1
    assert k["overall"]["accuracy"] == 1.0
