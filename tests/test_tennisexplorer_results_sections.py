from datetime import date

from scripts.tennisexplorer_results_collector import parse_results


def _result_table(a: str, b: str, clock: str, sa: int, sb: int, detail_id: int) -> str:
    return f"""
    <table class="result"><tbody>
      <tr class="head flags"><td class="t-name">Cincinnati</td></tr>
      <tr>
        <td class="first time">{clock}</td>
        <td class="t-name">{a}</td>
        <td>{sa}</td>
        <td class="course">1.70</td><td class="coursew">2.10</td>
        <td><a href="/match-detail/?id={detail_id}">info</a></td>
      </tr>
      <tr><td></td><td class="t-name">{b}</td><td>{sb}</td></tr>
    </tbody></table>
    """


def test_results_use_visible_date_and_exclude_neighbor_day():
    html = f"""
    <html><body>
      <div>12. 08. 2026</div>
      {_result_table('Old A.','Old B.','20:00',2,0,1)}
      <div>13. 08. 2026</div>
      {_result_table('Shapovalov D.','Mannarino A.','20:00',2,1,2)}
    </body></html>
    """
    rows = parse_results(html, date(2026, 8, 13), "https://www.tennisexplorer.com")
    assert len(rows) == 1
    assert rows[0]["home_team"] == "Shapovalov D."
    assert rows[0]["away_team"] == "Mannarino A."
    assert rows[0]["schedule_section_date"] == "2026-08-13"
    assert rows[0]["schedule_date_verified"] is True
