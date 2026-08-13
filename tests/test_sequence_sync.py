import json
from types import SimpleNamespace

from tennis_quant.sequence import freeze_sequence
from tennis_quant.sequence_sync import update_all_sequence_results, update_all_sequence_schedules


def _row(idx: int) -> dict:
    return {
        "status": "REJECTED",
        "match": {
            "match_id": f"m{idx}",
            "date": "2026-08-13",
            "time": "",
            "tournament": "ATP Test",
            "surface": "Hard",
            "player_a": {"key": f"p{idx}", "name": f"Player {idx}"},
            "player_b": {"key": f"o{idx}", "name": f"Opponent {idx}"},
        },
        "selected_player": {"key": f"p{idx}", "name": f"Player {idx}"},
        "opponent": {"key": f"o{idx}", "name": f"Opponent {idx}"},
        "odd": 1.80,
        "selected_market": {"best_odd": 1.80, "bookmakers": 5},
        "final_probability": 0.60 + idx * 0.01,
        "confidence": 55 + idx,
        "edge_pp": 2 + idx,
        "data_quality": 0.9,
        "disagreement_pp": 5.0,
        "signals": {"elo": 0.60},
        "reject_reasons": [],
    }


def _board() -> dict:
    return {
        "board_date": "2026-08-13",
        "model_version": "test-model",
        "last_run_at": "2026-08-12T12:00:00-03:00",
        "approved": [],
        "shadow": [],
        "rejected": [_row(i) for i in range(1, 7)],
    }


def test_schedule_sync_appends_moved_date_without_changing_pick(tmp_path):
    frozen = freeze_sequence(tmp_path, _board())
    game = frozen["games"][0]
    original_player = dict(game["selected_player"])
    fixture = SimpleNamespace(
        match_id=game["match_id"],
        date="2026-08-14",
        time="16:00",
        player_a=SimpleNamespace(name=game["match"]["player_a"]["name"]),
        player_b=SimpleNamespace(name=game["match"]["player_b"]["name"]),
        raw={"source": "TennisExplorer schedule"},
    )

    result = update_all_sequence_schedules(tmp_path, [fixture])
    assert result["matched_games"] == 1

    saved = json.loads((tmp_path / "data" / "sequences" / "2026-08-13.json").read_text())
    synced = next(row for row in saved["games"] if row["match_id"] == game["match_id"])
    assert synced["selected_player"] == original_player
    assert synced["scheduled_date_current"] == "2026-08-14"
    assert synced["scheduled_time_current"] == "16:00"
    assert synced["schedule_changed_from_freeze"] is True


def test_schedule_sync_falls_back_to_player_pair_when_match_id_changes(tmp_path):
    frozen = freeze_sequence(tmp_path, _board())
    game = frozen["games"][0]
    fixture = SimpleNamespace(
        match_id="new-source-id",
        date="2026-08-14",
        time="20:00",
        player_a=SimpleNamespace(name=game["match"]["player_b"]["name"]),
        player_b=SimpleNamespace(name=game["match"]["player_a"]["name"]),
        raw={"source": "TennisExplorer tournament page"},
    )

    result = update_all_sequence_schedules(tmp_path, [fixture])
    assert result["matched_games"] == 1
    assert result["player_pair_matches"] == 1

    saved = json.loads((tmp_path / "data" / "sequences" / "2026-08-13.json").read_text())
    synced = next(row for row in saved["games"] if row["match_id"] == game["match_id"])
    assert synced["selected_player"] == game["selected_player"]
    assert synced["scheduled_date_current"] == "2026-08-14"
    assert synced["scheduled_time_current"] == "20:00"
    assert synced["schedule_match_method"] == "PLAYER_PAIR"


def test_result_sync_finds_original_sequence_after_match_moves_day(tmp_path):
    frozen = freeze_sequence(tmp_path, _board())
    game = frozen["games"][0]
    selected = game["selected_player"]
    opponent = game["opponent"]
    fixture = SimpleNamespace(
        match_id=game["match_id"],
        date="2026-08-14",
        time="18:30",
        winner="First Player",
        player_a=SimpleNamespace(key=selected["key"], name=selected["name"]),
        player_b=SimpleNamespace(key=opponent["key"], name=opponent["name"]),
        raw={"event_final_result": "2 - 1"},
    )

    result = update_all_sequence_results(tmp_path, [fixture])
    assert result["resolved_games"] == 1

    saved = json.loads((tmp_path / "data" / "sequences" / "2026-08-13.json").read_text())
    synced = next(row for row in saved["games"] if row["match_id"] == game["match_id"])
    assert synced["selected_player"] == selected
    assert synced["result"]["status"] == "HIT"
    assert synced["result"]["actual_date"] == "2026-08-14"
    assert synced["result"]["actual_time"] == "18:30"
    assert synced["result"]["score"] == "2 - 1"


def test_result_sync_falls_back_to_pair_and_preserves_frozen_pick(tmp_path):
    frozen = freeze_sequence(tmp_path, _board())
    game = frozen["games"][0]
    selected = game["selected_player"]
    opponent = game["opponent"]
    fixture = SimpleNamespace(
        match_id="different-result-source-id",
        date="2026-08-14",
        time="21:30",
        winner="Second Player",
        player_a=SimpleNamespace(key="other", name=opponent["name"]),
        player_b=SimpleNamespace(key="renumbered", name=selected["name"]),
        raw={"event_final_result": "1 - 2"},
    )

    result = update_all_sequence_results(tmp_path, [fixture])
    assert result["resolved_games"] == 1
    assert result["player_pair_matches"] == 1

    saved = json.loads((tmp_path / "data" / "sequences" / "2026-08-13.json").read_text())
    synced = next(row for row in saved["games"] if row["match_id"] == game["match_id"])
    assert synced["selected_player"] == selected
    assert synced["result"]["status"] == "HIT"
    assert synced["result"]["match_method"] == "PLAYER_PAIR"
