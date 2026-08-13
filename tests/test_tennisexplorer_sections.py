from datetime import date

from bs4 import BeautifulSoup

from scripts.tennisexplorer_schedule_collector_v2 import parse_target_day
from scripts.tennisexplorer_sections import table_section_date


def _table(name_a: str, name_b: str, clock: str, odd_a: str = "1.70", odd_b: str = "2.10") -> str:
    return f"""
    <table class="result"><tbody>
      <tr class="head flags"><td class="t-name">Cincinnati</td></tr>
      <tr><td class="first time">{clock}</td><td class="t-name">{name_a}</td><td class="course">{odd_a}</td><td class="coursew">{odd_b}</td><td><a href="/match-detail/?id=123">info</a></td></tr>
      <tr><td></td><td class="t-name">{name_b}</td></tr>
    </tbody></table>
    """


def test_table_section_date_reads_nearest_heading():
    html = f"<div class='date'>13. 08. 2026</div>{_table('A','B','20:00')}"
    soup = BeautifulSoup(html, "html.parser")
    assert table_section_date(soup.find("table")) == date(2026, 8, 13)


def test_parse_target_day_excludes_neighbor_date_section():
    html = f"""
    <html><body>
      <div class="date">13. 08. 2026</div>
      {_table('Shapovalov D.','Mannarino A.','20:00')}
      <div class="date">14. 08. 2026</div>
      {_table('Royer V.','Tsitsipas S.','16:00')}
    </body></html>
    """
    rows, summary = parse_target_day(html, date(2026, 8, 13), "https://www.tennisexplorer.com")
    assert len(rows) == 1
    assert rows[0]["home_team"] == "Shapovalov D."
    assert rows[0]["away_team"] == "Mannarino A."
    assert rows[0]["schedule_section_date"] == "2026-08-13"
    assert rows[0]["schedule_verification_method"] == "VISIBLE_DATE_SECTION"
    assert summary["skipped_other_day"] == 1


def test_parse_target_day_uses_requested_neighbor_section():
    html = f"""
    <html><body>
      <div>13. 08. 2026</div>{_table('Shapovalov D.','Mannarino A.','20:00')}
      <div>14. 08. 2026</div>{_table('Royer V.','Tsitsipas S.','16:00')}
    </body></html>
    """
    rows, _ = parse_target_day(html, date(2026, 8, 14), "https://www.tennisexplorer.com")
    assert [(r["home_team"], r["away_team"]) for r in rows] == [("Royer V.", "Tsitsipas S.")]
