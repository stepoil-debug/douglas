from datetime import date
from types import SimpleNamespace

from tennis_quant.failure import classify_postmortem
from tennis_quant.pipeline import _fresh_ranking, _recover_surface


class _Store:
    def __init__(self):
        self.latest_rank = {
            "fresh": {"date": "20260810"},
            "stale": {"date": "20260728"},
        }
        self.calls = []

    def surface_for_tournament(self, tournament: str, year: int):
        self.calls.append((tournament, year))
        return "Hard" if year == 2025 else None


class _Provider:
    def __init__(self):
        self.sackmann = _Store()


def test_surface_recovers_from_previous_tournament_edition():
    provider = _Provider()
    match = SimpleNamespace(surface=None, tournament="ATP Cincinnati")
    surface = _recover_surface(provider, match, date(2026, 8, 13), lookback_years=3)
    assert surface == "Hard"
    assert match.surface == "Hard"
    assert provider.sackmann.calls[:2] == [("ATP Cincinnati", 2026), ("ATP Cincinnati", 2025)]


def test_stale_ranking_is_removed_from_ensemble():
    provider = _Provider()
    standings = {
        "fresh": {"place": 15, "points": 2500},
        "stale": {"place": 22, "points": 1800},
    }
    target = date(2026, 8, 13)
    assert _fresh_ranking(provider, standings, "fresh", target, max_age_days=8) == standings["fresh"]
    assert _fresh_ranking(provider, standings, "stale", target, max_age_days=8) is None


def test_low_confidence_miss_is_uncertainty_not_fake_market_error():
    postmortem = classify_postmortem({
        "surface": None,
        "final_probability": 0.529,
        "confidence": 37.9,
        "data_quality": 0.90,
        "edge_pp": -2.6,
        "disagreement_pp": 5.8,
        "signals": {"market": 0.556, "elo": 0.552},
    })
    assert "ERR-UNC" in postmortem["tags"]
    assert "ERR-SUR" in postmortem["tags"]
    assert "ERR-MKT" not in postmortem["tags"]


def test_material_model_market_opposition_is_market_error_hypothesis():
    postmortem = classify_postmortem({
        "surface": "Hard",
        "final_probability": 0.62,
        "confidence": 75.0,
        "data_quality": 0.92,
        "edge_pp": 8.0,
        "disagreement_pp": 8.0,
        "signals": {"market": 0.45, "surface_elo": 0.67, "elo": 0.65},
    })
    assert "ERR-MKT" in postmortem["tags"]
