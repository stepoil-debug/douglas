from datetime import date

from scripts.tennisexplorer_collector import parse_matches


def test_parse_tennisexplorer_atp_schedule_pair():
    html = """
    <html><body>
      <table class="result"><tbody>
        <tr class="head flags"><td class="t-name"><a href="/cincinnati/2026/atp-men/">Cincinnati</a></td></tr>
        <tr>
          <td class="first time">17:10</td>
          <td class="t-name"><a href="/player/fritz/">Fritz T. (4)</a></td>
          <td class="course">1.66</td>
          <td class="coursew">2.23</td>
          <td><a href="/match-detail/?id=123">info</a></td>
        </tr>
        <tr>
          <td></td>
          <td class="t-name"><a href="/player/humbert/">Humbert U. (20)</a></td>
        </tr>
      </tbody></table>
    </body></html>
    """
    rows = parse_matches(html, date(2026, 8, 11), "https://www.tennisexplorer.com")
    assert len(rows) == 1
    row = rows[0]
    assert row["home_team"] == "Fritz T."
    assert row["away_team"] == "Humbert U."
    assert row["league_name"] == "ATP Cincinnati"
    assert row["match_date"] == "2026-08-11 20:10:00 UTC"
    assert row["match_winner_market"][0]["player_1"] == "1.660"
    assert row["match_winner_market"][0]["player_2"] == "2.230"
    assert row["match_link"].endswith("/match-detail/?id=123")


def test_parse_tennisexplorer_excludes_lower_level_tournaments():
    html = """
    <table class="result"><tbody>
      <tr class="head flags"><td class="t-name">Winston-Salem challenger</td></tr>
      <tr><td class="first time">14:00</td><td class="t-name">Player A.</td><td class="course">1.70</td><td class="course">2.10</td></tr>
      <tr><td></td><td class="t-name">Player B.</td></tr>
    </tbody></table>
    """
    assert parse_matches(html, date(2026, 8, 11), "https://www.tennisexplorer.com") == []
