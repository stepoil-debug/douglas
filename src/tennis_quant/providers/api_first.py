from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from tennis_quant.providers.api_tennis import ApiTennisProvider
from tennis_quant.providers.public_tennis import PublicTennisProvider


class ApiFirstTennisProvider:
    """Use API-Tennis for the live D+1 board and public ATP history as fallback/base."""

    history_source_id = PublicTennisProvider.history_source_id

    def __init__(self, root: Path, api_key: str):
        self.root = root
        self.api = ApiTennisProvider(api_key)
        self.public = PublicTennisProvider(root)
        self.sackmann = self.public.sackmann
        self.live_source = "API-Tennis"
        self.current_context_date = date.today()

    @property
    def source_requests(self) -> int:
        return int(self.api.source_requests) + int(self.public.source_requests)

    def fixtures(self, target_date: date):
        self.current_context_date = target_date
        self.public.current_context_date = target_date
        rows = self.api.fixtures(target_date)
        if not rows:
            raise RuntimeError("API-Tennis returned zero ATP Singles fixtures")
        self.live_source = "API-Tennis"
        return rows

    def odds(self, target_date: date) -> dict[str, Any]:
        self.current_context_date = target_date
        result = self.api.odds(target_date)
        if not result:
            raise RuntimeError("API-Tennis returned no Match Winner odds")
        return result

    def fixtures_range(self, start: date, end: date):
        # Historical bootstrap/results stay on the public ATP dataset so API quota
        # is spent only where it adds value: the live/future board.
        return self.public.fixtures_range(start, end)

    def standings(self, tour: str = "ATP") -> dict[str, dict[str, Any]]:
        try:
            rows = self.api.standings(tour)
            if rows:
                return rows
        except Exception:
            pass
        return self.public.standings(tour)

    def h2h(self, player_a_key: str, player_b_key: str) -> dict[str, Any]:
        try:
            result = self.api.h2h(player_a_key, player_b_key)
            if result:
                return result
        except Exception:
            pass
        return self.public.h2h(player_a_key, player_b_key)

    def player_profile(self, player_key: str) -> dict[str, Any]:
        try:
            result = self.api.player_profile(player_key)
            if result:
                return result
        except Exception:
            pass
        return self.public.player_profile(player_key)

    def player_history(self, player_key: str, start: date, end: date):
        return self.public.player_history(player_key, start, end)
