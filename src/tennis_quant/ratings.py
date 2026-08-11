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
        self.data = {"global": {}, "surface": {}, "processed_matches": []}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        self.data.setdefault("global", {})
        self.data.setdefault("surface", {})
        self.data.setdefault("processed_matches", [])

    def get(self, player_key: str, surface: str | None = None) -> tuple[float, float]:
        global_rating = float(self.data["global"].get(player_key, DEFAULT_ELO))
        surface_key = (surface or "unknown").lower()
        surface_rating = float(self.data["surface"].get(surface_key, {}).get(player_key, global_rating))
        return global_rating, surface_rating

    def probability(self, a: str, b: str, surface: str | None = None) -> tuple[float, float]:
        a_g, a_s = self.get(a, surface)
        b_g, b_s = self.get(b, surface)
        return expected(a_g, b_g), expected(a_s, b_s)

    def record_match(self, match_id: str, winner_key: str, loser_key: str, surface: str | None = None) -> bool:
        processed = set(self.data["processed_matches"])
        if match_id in processed:
            return False

        w_g, _ = self.get(winner_key, surface)
        l_g, _ = self.get(loser_key, surface)
        new_w, new_l = update_pair(w_g, l_g)
        self.data["global"][winner_key] = new_w
        self.data["global"][loser_key] = new_l

        if surface:
            skey = surface.lower()
            bucket = self.data["surface"].setdefault(skey, {})
            w_s = float(bucket.get(winner_key, w_g))
            l_s = float(bucket.get(loser_key, l_g))
            new_ws, new_ls = update_pair(w_s, l_s)
            bucket[winner_key] = new_ws
            bucket[loser_key] = new_ls

        self.data["processed_matches"].append(match_id)
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
