from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Player:
    key: str
    name: str


@dataclass
class Match:
    match_id: str
    date: str
    time: str
    tournament: str
    event_type: str
    surface: str | None
    player_a: Player
    player_b: Player
    status: str = ""
    winner: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketSide:
    player_key: str
    best_odd: float | None
    median_odd: float | None
    fair_probability: float | None
    bookmakers: int
    bookmaker_odds: dict[str, float] = field(default_factory=dict)


@dataclass
class Candidate:
    match: Match
    selected_player: Player
    opponent: Player
    selected_market: MarketSide
    opponent_market: MarketSide
    signals: dict[str, float]
    final_probability: float
    market_probability: float
    edge_pp: float
    disagreement_pp: float
    data_quality: float
    confidence: float
    status: str = "REJECTED"
    rank: int | None = None
    reject_reasons: list[str] = field(default_factory=list)
    model_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["match"]["raw"] = {}
        return data
