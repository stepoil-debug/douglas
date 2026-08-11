from datetime import date

from scripts.tennisexplorer_results_collector import parse_results


def test_parse_finished_atp_match_from_results_table():
    html = """
    <html><body>
      <table class="result"><tbody>
        <tr class="head"><td class="t-name">Cincinnati</td></tr>
        <tr>
          <td class="first time">17:10</td>
          <td class="t-name"><a>Sinner J. (1)</a></td>
          <td>2</td><td>6</td><td>6</td>
          <td class="course">1.38</td><td class="coursew">3.10</td>
          <td><a href="/match-detail/?id=999">info</a></td>
        </tr>
        <tr>
          <td></td><td class="t-name"><a>Player B.</a></td><td>0</td><td>3</td><td>4</td>
        </tr>
      </tbody></table>
    </body></html>
    """
    rows = parse_results(html, date(2026, 8, 11), "https://www.tennisexplorer.com")
    assert len(rows) == 1
    row = rows[0]
    assert row["home_team"] == "Sinner J."
    assert row["away_team"] == "Player B."
    assert row["home_score"] == "2"
    assert row["away_score"] == "0"
    assert row["match_link"].endswith("/match-detail/?id=999")
