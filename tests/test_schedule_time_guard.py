import json
from datetime import datetime, timedelta, timezone

from scripts.refresh_sequence_times import _fixture
from scripts.schedule_time_guard import mark_unconfirmed_placeholder_times
from tennis_quant.sequence import freeze_sequence
from tennis_quant.sequence_sync import update_all_sequence_schedules


def _row(i: int, utc_time: str = "15:00:00") -> dict:
    return {
        "match_date": f"2026-08-13 {utc_time} UTC",
        "home_team": f"Player {i}A",
        "away_team": f"Player {i}B",
        "league_name": "ATP Cincinnati",
    }


def _utc(day: str, clock: str) -> str:
    local = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=-3)))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def test_repeated_noon_placeholder_is_not_treated_as_confirmed_time():
    rows = [_row(i) for i in range(20)]
    summary = mark_unconfirmed_placeholder_times(rows)
    assert summary["flagged"] == 20
    assert all(row["match_date"] == "" for row in rows)
    assert all(row["time_confirmed"] is False for row in rows)
    assert all(row["reported_local_time"] == "12:00" for row in rows)
    assert all(row["schedule_section_date"] == "2026-08-13" for row in rows)


def test_visible_date_does_not_make_mass_placeholder_time_confirmed():
    rows = [{
        "match_date": _utc("2026-08-14", "12:00"),
        "home_team": f"A {idx}",
        "away_team": f"B {idx}",
        "league_name": "ATP Cincinnati",
        "schedule_section_date": "2026-08-14",
        "schedule_date_verified": True,
        "schedule_verification_method": "VISIBLE_DATE_SECTION",
    } for idx in range(10)]
    summary = mark_unconfirmed_placeholder_times(rows)
    assert summary["flagged"] == 10
    assert all(row["match_date"] == "" for row in rows)
    assert all(row["schedule_section_date"] == "2026-08-14" for row in rows)
    assert all(row["time_confirmed"] is False for row in rows)


def test_detail_verified_time_survives_repeated_clock():
    rows = [{
        "match_date": _utc("2026-08-14", "12:00"),
        "home_team": f"A {idx}",
        "away_team": f"B {idx}",
        "league_name": "ATP Cincinnati",
        "schedule_section_date": "2026-08-14",
        "schedule_date_verified": True,
        "schedule_verified_local_time": "12:00",
    } for idx in range(10)]
    summary = mark_unconfirmed_placeholder_times(rows)
    assert summary["flagged"] == 0
    assert all(row["match_date"] for row in rows)
    assert all(row["time_confirmed"] is True for row in rows)


def test_normal_varied_schedule_remains_confirmed():
    times = ["14:00:00", "15:00:00", "16:00:00", "17:00:00", "18:00:00", "19:00:00"]
    rows = [_row(i, times[i]) for i in range(len(times))]
    summary = mark_unconfirmed_placeholder_times(rows)
    assert summary["flagged"] == 0
    assert all(row["match_date"] for row in rows)
    assert all(row["time_confirmed"] is True for row in rows)


def test_date_only_schedule_clears_old_placeholder_without_changing_pick(tmp_path):
    board = {
        "board_date": "2026-08-13",
        "model_version": "test",
        "last_run_at": "2026-08-12T12:00:00-03:00",
        "approved": [],
        "shadow": [],
        "rejected": [{
            "status": "REJECTED",
            "match": {
                "match_id": "old-id",
                "date": "2026-08-13",
                "time": "",
                "tournament": "ATP Cincinnati",
                "surface": "Hard",
                "player_a": {"key": "a", "name": "Royer V."},
                "player_b": {"key": "b", "name": "Tsitsipas S."},
            },
            "selected_player": {"key": "b", "name": "Tsitsipas S."},
            "opponent": {"key": "a", "name": "Royer V."},
            "odd": 2.10,
            "selected_market": {"best_odd": 2.10, "bookmakers": 5},
            "final_probability": 0.71,
            "confidence": 55,
            "edge_pp": -1,
            "data_quality": 1.0,
            "disagreement_pp": 8,
            "signals": {},
            "reject_reasons": [],
        }],
    }
    frozen = freeze_sequence(tmp_path, board)
    original = frozen["games"][0]["selected_player"]
    path = tmp_path / "data" / "sequences" / "2026-08-13.json"
    payload = json.loads(path.read_text())
    payload["games"][0]["scheduled_date_current"] = "2026-08-14"
    payload["games"][0]["scheduled_time_current"] = "12:00"
    path.write_text(json.dumps(payload))

    fixture = _fixture({
        "match_date": "",
        "home_team": "Royer V.",
        "away_team": "Tsitsipas S.",
        "league_name": "ATP Cincinnati",
        "match_link": "https://example.test/match-detail/?id=777",
        "schedule_section_date": "2026-08-14",
        "schedule_date_verified": True,
        "time_confirmed": False,
    })
    assert fixture is not None
    assert fixture.date == "2026-08-14"
    assert fixture.time == ""

    result = update_all_sequence_schedules(tmp_path, [fixture])
    assert result["matched_games"] == 1
    saved = json.loads(path.read_text())
    game = saved["games"][0]
    assert game["selected_player"] == original
    assert game["scheduled_date_current"] == "2026-08-14"
    assert game["scheduled_time_current"] is None
    assert game["schedule_time_status"] == "PENDING"
