from datetime import date

from scripts.tennisexplorer_tournament_fallback import discover_tournament_links, parse_tournament_page


def test_discover_tournament_links_keeps_main_atp_only():
    html = """
    <table class='result'><tbody>
      <tr class='head flags'><td class='t-name'><a href='/cincinnati/2026/atp-men/'>Cincinnati</a></td></tr>
      <tr class='head flags'><td class='t-name'><a href='/cincinnati/2026/atp-men/?phase=qualification'>Cincinnati qual.</a></td></tr>
      <tr class='head flags'><td class='t-name'><a href='/winston-salem/2026/challenger-men/'>Winston-Salem challenger</a></td></tr>
      <tr class='head flags'><td class='t-name'><a href='/cincinnati/2026/wta-women/'>Cincinnati WTA</a></td></tr>
    </tbody></table>
    """
    links = discover_tournament_links(html, "https://www.tennisexplorer.com", 2026)
    assert links == [("Cincinnati", "https://www.tennisexplorer.com/cincinnati/2026/atp-men/")]


def test_parse_tournament_page_only_target_date():
    html = """
    <html><body><h1>Cincinnati 2026 (USA)</h1>
    <table class='result'><tbody>
      <tr>
        <td class='first time'>12.08.<br>14:30</td><td>R16</td>
        <td class='t-name'><a href='/player/fritz/'>Fritz T. (4)</a></td>
        <td class='course'>1.66</td><td class='coursew'>2.23</td>
        <td><a href='/match-detail/?id=12'>info</a></td>
      </tr>
      <tr><td></td><td></td><td class='t-name'><a href='/player/humbert/'>Humbert U.</a></td></tr>
      <tr>
        <td class='first time'>13.08.<br>15:00</td><td>QF</td>
        <td class='t-name'>Other A.</td><td class='course'>1.80</td><td class='coursew'>2.00</td>
      </tr>
      <tr><td></td><td></td><td class='t-name'>Other B.</td></tr>
    </tbody></table></body></html>
    """
    rows = parse_tournament_page(html, date(2026, 8, 12), "https://www.tennisexplorer.com", "Cincinnati")
    assert len(rows) == 1
    row = rows[0]
    assert row["home_team"] == "Fritz T."
    assert row["away_team"] == "Humbert U."
    assert row["match_date"] == "2026-08-12 17:30:00 UTC"
    assert row["match_winner_market"][0]["player_1"] == "1.660"
    assert row["match_winner_market"][0]["player_2"] == "2.230"
