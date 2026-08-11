from __future__ import annotations

import json
from pathlib import Path

DEFAULT_ELO = 1500.0
K = 28.0


def expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update_pair(winner: float, loser: float, k: float = K) -> tuple[float, float]:
    p = expected(winner, loser)
    delta = k * (1.0 - p)
    return winner + delta, loser - delta


class RatingStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"global": {}, "surface": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, player_key: str, surface: str | None = None) -> tuple[float, float]:
        global_rating = float(self.data.get("global", {}).get(player_key, DEFAULT_ELO))
        surface_key = (surface or "unknown").lower()
        surface_rating = float(self.data.get("surface", {}).get(surface_key, {}).get(player_key, global_rating))
        return global_rating, surface_rating

    def probability(self, a: str, b: str, surface: str | None = None) -> tuple[float, float]:
        a_g, a_s = self.get(a, surface)
        b_g, b_s = self.get(b, surface)
        return expected(a_g, b_g), expected(a_s, b_s)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
