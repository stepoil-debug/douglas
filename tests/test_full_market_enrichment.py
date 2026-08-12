from scripts.tennisexplorer_collector import _needs_detail


def test_extreme_odds_still_request_bookmaker_detail():
    record = {
        "match_winner_market": [{
            "player_1": "1.28",
            "player_2": "3.59",
            "bookmaker_name": "TennisExplorer avg",
        }]
    }
    assert _needs_detail(record) is True


def test_invalid_market_does_not_request_detail():
    assert _needs_detail({"match_winner_market": []}) is False
    assert _needs_detail({"match_winner_market": [{"player_1": "", "player_2": "3.00"}]}) is False
