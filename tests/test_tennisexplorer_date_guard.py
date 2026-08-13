from datetime import date

from scripts.tennisexplorer_date_guard import parse_detail_schedule


def test_parse_detail_today_schedule():
    html = "<html><body><h1>A - B</h1><div>Today, 20:00, Cincinnati, 1. round, hard</div></body></html>"
    actual, clock = parse_detail_schedule(html, date(2026, 8, 13))
    assert actual == date(2026, 8, 13)
    assert clock == "20:00"


def test_parse_detail_tomorrow_schedule():
    html = "<html><body><h1>A - B</h1><div>Tomorrow, 16:00, Cincinnati, 1. round, hard</div></body></html>"
    actual, clock = parse_detail_schedule(html, date(2026, 8, 13))
    assert actual == date(2026, 8, 14)
    assert clock == "16:00"


def test_parse_detail_explicit_schedule():
    html = "<html><body><div>14.08.2026, 18:30, Cincinnati</div></body></html>"
    actual, clock = parse_detail_schedule(html, date(2026, 8, 13))
    assert actual == date(2026, 8, 14)
    assert clock == "18:30"
