from datetime import date
from pathlib import Path

from tennis_quant.domain import Match, Player
from tennis_quant.pipeline import analyze_day


class FakeProvider:
    history_source_id = "test-full-board"
    source_requests = 0

    def __init__(self):
        self.match = Match(
            match_id="m-outside-range",
            date="2026-08-13",
            time="12:00",
            tournament="ATP Test",
            event_type="ATP Singles",
            surface="Hard",
            player_a=Player("p1", "Player One"),
            player_b=Player("p2", "Player Two"),
            status="",
            winner=None,
        )
        self.h2h_count = 0

    def fixtures(self, target_date):
        return [self.match]

    def odds(self, target_date):
        # Neither side is inside the 1.50-2.00 execution range. The match must
        # still receive the complete model pass and only be rejected afterwards.
        return {
            self.match.match_id: {
                "Home/Away": {
                    "Home": {"Book A": 1.25, "Book B": 1.24},
                    "Away": {"Book A": 4.50, "Book B": 4.60},
                }
            }
        }

    def fixtures_range(self, start, end):
        return []

    def standings(self, tour="ATP"):
        return {}

    def h2h(self, player_a_key, player_b_key):
        self.h2h_count += 1
        return {"H2H": [], "firstPlayerResults": [], "secondPlayerResults": []}

    def player_profile(self, player_key):
        return {}

    def player_history(self, player_key, start, end):
        return []


def _cfg():
    return {
        "model_version": "test-full-board",
        "bootstrap_days": 365,
        "surface_lookback_years": 3,
        "ranking_max_age_days": 8,
        "selection": {
            "min_odd": 1.50,
            "max_odd": 2.00,
            "max_approved": 10,
            "shadow_size": 10,
            "min_final_probability": 0.0,
            "min_edge_pp": -100.0,
            "min_confidence": 0.0,
            "min_data_quality": 0.0,
            "max_disagreement_pp": 100.0,
            "allow_qualification": True,
        },
        "ensemble_weights": {
            "market": 1.0,
            "elo": 0.0,
            "surface_elo": 0.0,
            "ranking": 0.0,
            "recent_form": 0.0,
            "season_profile": 0.0,
            "fatigue": 0.0,
            "serve": 0.0,
            "h2h": 0.0,
        },
        "confidence_weights": {
            "probability": 0.30,
            "edge": 0.27,
            "agreement": 0.20,
            "data_quality": 0.23,
        },
    }


def test_out_of_range_match_is_fully_analyzed_before_selection(tmp_path: Path):
    provider = FakeProvider()
    payload = analyze_day(provider, date(2026, 8, 13), _cfg(), tmp_path, h2h_budget=0)

    assert payload["analysis_policy"] == "ALL_PREMATCH_WITH_MARKET_BEFORE_SELECTION"
    assert payload["prematch_atp_singles"] == 1
    assert payload["matches_with_odds"] == 1
    assert payload["deep_analyzed_matches"] == 1
    assert payload["fully_analyzed_matches"] == 1
    assert payload["target_odd_pool_matches"] == 0
    assert payload["candidate_sides"] == 2
    assert payload["h2h_calls"] == 1
    assert payload["h2h_budget_effective"] >= 1
    assert provider.h2h_count == 1
    assert len(payload["approved"]) == 0
    assert len(payload["rejected"]) == 2
    assert all("ODD_OUT_OF_RANGE" in row["reject_reasons"] for row in payload["rejected"])
    assert all(row["selected_market"]["bookmaker_odds"] for row in payload["rejected"])
