from datetime import date
from pathlib import Path

from tennis_quant.features import fatigue_readiness, ranking_probability, serve_strength
from tennis_quant.market import consensus_market, no_vig_probability
from tennis_quant.prediction import confidence_score, disagreement_pp, weighted_probability
from tennis_quant.providers.public_tennis import SackmannStore, odds_home_away, player_aliases
from tennis_quant.ratings import RatingStore, margin_k
from tennis_quant.storage import write_snapshot


def test_no_vig_sums_to_one():
    a, b = no_vig_probability(1.60, 2.40)
    assert abs((a + b) - 1.0) < 1e-12


def test_consensus_uses_paired_books():
    out = consensus_market({"A": "1.60", "B": "1.62"}, {"A": "2.40", "B": "2.35"})
    assert out["bookmakers"] == 2
    assert out["home_best"] == 1.62
    assert 0 < out["home_fair"] < 1


def test_weighted_probability_renormalizes_missing_signals():
    p = weighted_probability({"market": 0.60, "elo": 0.70}, {"market": 0.5, "elo": 0.5, "surface": 0.5})
    assert abs(p - 0.65) < 1e-9


def test_disagreement_and_confidence_are_bounded():
    d = disagreement_pp({"a": 0.7, "b": 0.7, "c": 0.7})
    assert d == 0
    c = confidence_score(0.72, 8.0, d, 1.0, {"probability": .3, "edge": .3, "agreement": .2, "data_quality": .2})
    assert 0 <= c <= 100


def test_snapshot_key_includes_selected_player(tmp_path: Path):
    base = {"match": {"match_id": "m1"}, "selected_player": {"key": "p1"}}
    other = {"match": {"match_id": "m1"}, "selected_player": {"key": "p2"}}
    a = write_snapshot(tmp_path, "2026-08-11", base)
    b = write_snapshot(tmp_path, "2026-08-11", other)
    assert a != b
    assert a.exists() and b.exists()


def test_elo_result_is_idempotent(tmp_path: Path):
    store = RatingStore(tmp_path / "ratings.json")
    assert store.record_match("m1", "a", "b", "Hard") is True
    first = store.get("a", "Hard")[0]
    assert first > 1500
    assert store.record_match("m1", "a", "b", "Hard") is False
    assert store.get("a", "Hard")[0] == first


def test_ranking_probability_uses_atp_points():
    p = ranking_probability({"place": "10", "points": "4000"}, {"place": "30", "points": "2000"})
    assert p is not None
    assert 0.60 < p < 0.72
    reverse = ranking_probability({"place": "30", "points": "2000"}, {"place": "10", "points": "4000"})
    assert reverse is not None
    assert abs((p + reverse) - 1.0) < 1e-9


def test_fatigue_penalizes_dense_recent_schedule():
    target = date(2026, 8, 11)
    busy = [{"event_date": "2026-08-10"}, {"event_date": "2026-08-09"}, {"event_date": "2026-08-08"}]
    rested = [{"event_date": "2026-08-04"}]
    busy_score, _ = fatigue_readiness(busy, target)
    rested_score, _ = fatigue_readiness(rested, target)
    assert rested_score > busy_score


def test_serve_strength_reads_inline_fixture_statistics():
    history = [{"statistics": [
        {"player_key": "p1", "stat_name": "1st serve points won", "stat_value": "70%", "stat_won": 35, "stat_total": 50},
        {"player_key": "p1", "stat_name": "2nd serve points won", "stat_value": "55%", "stat_won": 11, "stat_total": 20},
    ]}]
    strength, seen = serve_strength(history, "p1")
    assert strength is not None
    assert 0.55 < strength < 0.70
    assert seen == 1


def test_margin_k_is_capped_and_rewards_clearer_set_margin():
    assert margin_k("2 - 0") > margin_k("2 - 1")
    assert margin_k("3 - 0") <= 28.0 * 1.24


def test_odds_harvester_market_is_adapted_to_engine_format():
    record = {"match_winner_market": [
        {"player_1": "1.63", "player_2": "2.35", "bookmaker_name": "Book A", "period": "FullTime"},
        {"player_1": "1.60", "player_2": "2.40", "bookmaker_name": "Book B", "period": "FullTime"},
    ]}
    out = odds_home_away(record)
    assert out["Home/Away"]["Home"] == {"Book A": 1.63, "Book B": 1.60}
    assert out["Home/Away"]["Away"] == {"Book A": 2.35, "Book B": 2.40}
    consensus = consensus_market(out["Home/Away"]["Home"], out["Home/Away"]["Away"])
    assert consensus["bookmakers"] == 2


def test_sackmann_alias_resolves_oddsportal_abbreviation(tmp_path: Path):
    store = SackmannStore(tmp_path)
    store.players["104925"] = "Novak Djokovic"
    for alias in player_aliases("Novak Djokovic"):
        store.alias_to_ids[alias].add("104925")
    resolved = store.resolve_player("Djokovic N.")
    assert resolved.key == "104925"
    assert resolved.name == "Novak Djokovic"


def test_elo_bootstrap_resets_when_data_source_changes(tmp_path: Path):
    store = RatingStore(tmp_path / "ratings.json")
    store.record_match("old-1", "api-a", "api-b", "Hard")
    store.mark_bootstrap("2025-01-01", "2025-12-31", 1, source="api-tennis")
    assert store.ensure_source("jeff-sackmann-v1") is True
    assert store.data["global"] == {}
    assert store.data["processed_matches"] == []
