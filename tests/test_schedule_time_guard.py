from scripts.schedule_time_guard import mark_unconfirmed_placeholder_times


def _row(i: int, utc_time: str = "15:00:00") -> dict:
    return {
        "match_date": f"2026-08-13 {utc_time} UTC",
        "home_team": f"Player {i}A",
        "away_team": f"Player {i}B",
        "league_name": "ATP Cincinnati",
    }


def test_repeated_noon_placeholder_is_not_treated_as_confirmed_time():
    rows = [_row(i) for i in range(20)]
    summary = mark_unconfirmed_placeholder_times(rows)
    assert summary["flagged"] == 20
    assert all(row["match_date"] == "" for row in rows)
    assert all(row["time_confirmed"] is False for row in rows)
    assert all(row["reported_local_time"] == "12:00" for row in rows)


def test_normal_varied_schedule_remains_confirmed():
    times = ["14:00:00", "15:00:00", "16:00:00", "17:00:00", "18:00:00", "19:00:00"]
    rows = [_row(i, times[i]) for i in range(len(times))]
    summary = mark_unconfirmed_placeholder_times(rows)
    assert summary["flagged"] == 0
    assert all(row["match_date"] for row in rows)
    assert all(row["time_confirmed"] is True for row in rows)
