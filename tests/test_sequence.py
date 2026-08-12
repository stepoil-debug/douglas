from types import SimpleNamespace

from tennis_quant.sequence import freeze_sequence, update_sequence_results


def _row(idx: int, probability: float, time: str = "") -> dict:
    return {
        "status": "REJECTED",
        "match": {
            "match_id": f"m{idx}",
            "date": "2026-08-13",
            "time": time,
            "tournament": "ATP Test",
            "surface": "Hard",
        },
        "selected_player": {"key": f"p{idx}", "name": f"Player {idx}"},
        "opponent": {"key": f"o{idx}", "name": f"Opponent {idx}"},
        "odd": 1.80,
        "selected_market": {"best_odd": 1.80, "bookmakers": 5, "bookmaker_odds": {"bet365": 1.80}},
        "final_probability": probability,
        "confidence": 55 + idx,
        "edge_pp": 3 + idx,
        "data_quality": 0.9,
        "disagreement_pp": 5.0,
        "signals": {"elo": probability},
        "reject_reasons": ["CONFIDENCE_TOO_LOW"],
    }


def _board(offset: float = 0.0) -> dict:
    return {
        "board_date": "2026-08-13",
        "model_version": "test-model",
        "last_run_at": "2026-08-12T12:00:00-03:00",
        "approved": [],
        "shadow": [],
        "rejected": [_row(i, 0.55 + i * 0.01 + offset) for i in range(1, 8)],
    }


def test_sequence_is_frozen_once(tmp_path):
    first = freeze_sequence(tmp_path, _board())
    assert first["status"] == "FROZEN"
    assert len(first["games"]) == 6
    names = [game["selected_player"]["name"] for game in first["games"]]

    second_board = _board(0.20)
    second_board["rejected"][0]["selected_player"]["name"] = "CHANGED PLAYER"
    second = freeze_sequence(tmp_path, second_board)

    assert [game["selected_player"]["name"] for game in second["games"]] == names
    assert "CHANGED PLAYER" not in names


def test_sequence_results_append_without_replacing_pick(tmp_path):
    frozen = freeze_sequence(tmp_path, _board())
    game = frozen["games"][0]
    selected = game["selected_player"]
    opponent = game["opponent"]
    fixture = SimpleNamespace(
        match_id=game["match_id"],
        winner="First Player",
        player_a=SimpleNamespace(key=selected["key"], name=selected["name"]),
        player_b=SimpleNamespace(key=opponent["key"], name=opponent["name"]),
        raw={"event_final_result": "2 - 0"},
    )

    updated = update_sequence_results(tmp_path, "2026-08-13", [fixture])
    resolved = next(row for row in updated["games"] if row["match_id"] == game["match_id"])

    assert resolved["selected_player"] == selected
    assert resolved["result"]["status"] == "HIT"
    assert resolved["result"]["score"] == "2 - 0"
    assert updated["summary"]["resolved"] == 1
    assert updated["summary"]["hits"] == 1
