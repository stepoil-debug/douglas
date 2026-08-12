from tennis_quant.domain import Candidate, MarketSide, Match, Player
from tennis_quant.selection import rank_candidates


def _candidate(key: str, time: str, confidence: float, odd: float = 1.75) -> Candidate:
    a = Player(f"{key}-a", f"Player {key} A")
    b = Player(f"{key}-b", f"Player {key} B")
    match = Match(
        match_id=f"m-{key}",
        date="2026-08-13",
        time=time,
        tournament="ATP Test",
        event_type="ATP Singles",
        surface="Hard",
        player_a=a,
        player_b=b,
    )
    return Candidate(
        match=match,
        selected_player=a,
        opponent=b,
        selected_market=MarketSide(a.key, odd, odd, 0.57, 8),
        opponent_market=MarketSide(b.key, 2.10, 2.10, 0.43, 8),
        signals={"market": 0.57, "elo": 0.72},
        final_probability=0.70,
        market_probability=0.57,
        edge_pp=13.0,
        disagreement_pp=5.0,
        data_quality=0.90,
        confidence=confidence,
        model_version="test",
    )


def _cfg() -> dict:
    return {
        "selection": {
            "min_odd": 1.5,
            "max_odd": 2.0,
            "max_approved": 10,
            "shadow_size": 10,
            "min_entry_gap_minutes": 210,
            "require_known_start_time": True,
            "min_final_probability": 0.65,
            "min_edge_pp": 3.5,
            "min_confidence": 72.0,
            "min_data_quality": 0.62,
            "max_disagreement_pp": 12.5,
            "allow_qualification": False,
        }
    }


def test_approved_entries_are_spaced_and_ordered():
    rows = [
        _candidate("early", "12:00", 80),
        _candidate("conflict", "13:30", 88),
        _candidate("late", "16:00", 82),
        _candidate("later", "20:00", 79),
    ]
    ranked = rank_candidates(rows, _cfg())
    approved = [r for r in ranked if r.status == "APPROVED"]
    assert [r.match.time for r in approved] == ["12:00", "16:00", "20:00"]
    assert [r.rank for r in approved] == [1, 2, 3]
    conflict = next(r for r in rows if r.match.time == "13:30")
    assert conflict.status == "SHADOW"
    assert conflict.reject_reasons == ["TIME_WINDOW_CONFLICT"]


def test_best_game_wins_when_only_one_time_window_is_available():
    rows = [
        _candidate("a", "12:00", 78),
        _candidate("b", "12:30", 91),
        _candidate("c", "13:00", 82),
    ]
    rank_candidates(rows, _cfg())
    approved = [r for r in rows if r.status == "APPROVED"]
    assert len(approved) == 1
    assert approved[0].confidence == 91


def test_unknown_start_time_is_not_approved_for_sequential_plan():
    row = _candidate("unknown", "", 90)
    rank_candidates([row], _cfg())
    assert row.status == "SHADOW"
    assert row.reject_reasons == ["START_TIME_UNCONFIRMED"]
