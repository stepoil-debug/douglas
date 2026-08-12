import json

from tennis_quant.domain import Match, Player
from tennis_quant.history import record_analysis_history, update_history_results


def test_daily_history_keeps_bookmakers_and_final_result(tmp_path):
    player_a = Player("a", "Player A")
    player_b = Player("b", "Player B")
    match = Match(
        match_id="m1",
        date="2026-08-11",
        time="14:00",
        tournament="ATP Test",
        event_type="ATP Singles",
        surface="Hard",
        player_a=player_a,
        player_b=player_b,
    )
    odds = {
        "m1": {
            "Home/Away": {
                "Home": {"Betano": 1.75, "Pinnacle": 1.78},
                "Away": {"Betano": 2.05, "Pinnacle": 2.08},
            }
        }
    }
    candidate = {
        "match": {"match_id": "m1"},
        "selected_player": {"key": "a", "name": "Player A"},
        "opponent": {"key": "b", "name": "Player B"},
        "selected_market": {"best_odd": 1.78, "bookmakers": 2},
        "status": "APPROVED",
        "rank": 1,
        "final_probability": 0.72,
        "market_probability": 0.58,
        "edge_pp": 14.0,
        "confidence": 84.0,
        "data_quality": 0.85,
        "disagreement_pp": 5.0,
        "reject_reasons": [],
        "signals": {"market": 0.58, "elo": 0.74},
        "model_version": "test-v1",
    }

    ledger = record_analysis_history(tmp_path, "2026-08-11", [match], odds, [candidate], "test-v1", "TestSource")
    game = ledger["games"][0]
    assert game["date"] == "2026-08-11"
    assert game["market"]["bookmakers"] == ["Betano", "Pinnacle"]
    assert game["analyses"][0]["bookmaker_odds"] == {"Betano": 1.75, "Pinnacle": 1.78}
    assert game["result"]["resolved"] is False
    assert len(game["snapshots"]) == 1
    assert ledger["summary"]["analyzed_games"] == 1
    assert ledger["summary"]["resolved_model_picks"] == 0

    # Same data should not create a duplicate market snapshot.
    ledger = record_analysis_history(tmp_path, "2026-08-11", [match], odds, [candidate], "test-v1", "TestSource")
    assert len(ledger["games"][0]["snapshots"]) == 1

    match.status = "Finished"
    match.winner = "First Player"
    match.raw["event_final_result"] = "2 - 0"
    update_history_results(tmp_path, "2026-08-11", [match])

    saved = json.loads((tmp_path / "data" / "history" / "2026-08-11.json").read_text(encoding="utf-8"))
    assert saved["games"][0]["result"]["winner"]["name"] == "Player A"
    assert saved["games"][0]["result"]["score"] == "2 - 0"
    assert saved["summary"]["wins"] == 1
    assert saved["summary"]["accuracy"] == 1.0
    assert saved["summary"]["resolved_model_picks"] == 1
    assert saved["summary"]["model_hits"] == 1
    assert saved["summary"]["model_misses"] == 0
    assert saved["summary"]["model_accuracy"] == 1.0
