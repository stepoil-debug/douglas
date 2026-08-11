from tennis_quant.market import consensus_market, no_vig_probability
from tennis_quant.prediction import confidence_score, disagreement_pp, weighted_probability


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
