from __future__ import annotations

from datetime import date
from typing import Any

import requests

from tennis_quant.domain import Match, Player

BASE_URL = "https://api.api-tennis.com/tennis/"


class ApiTennisProvider:
    def __init__(self, api_key: str, timeout: int = 30):
        if not api_key:
            raise ValueError("API_TENNIS_KEY is required")
        self.api_key = api_key
        self.timeout = timeout

    def _get(self, method: str, **params: Any) -> Any:
        query = {"method": method, "APIkey": self.api_key, **params}
        response = requests.get(BASE_URL, params=query, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(f"API-Tennis error in {method}: {payload}")
        return payload.get("result")

    def fixtures(self, target_date: date) -> list[Match]:
        raw = self._get(
            "get_fixtures",
            date_start=target_date.isoformat(),
            date_stop=target_date.isoformat(),
            timezone="America/Sao_Paulo",
        ) or []
        matches: list[Match] = []
        for item in raw:
            event_type = str(item.get("event_type_type", ""))
            if "Singles" not in event_type:
                continue
            matches.append(Match(
                match_id=str(item.get("event_key")),
                date=str(item.get("event_date", target_date.isoformat())),
                time=str(item.get("event_time", "")),
                tournament=str(item.get("tournament_name", item.get("league_name", "Unknown"))),
                event_type=event_type,
                surface=item.get("surface") or item.get("tournament_surface"),
                player_a=Player(str(item.get("first_player_key")), str(item.get("event_first_player", "Player A"))),
                player_b=Player(str(item.get("second_player_key")), str(item.get("event_second_player", "Player B"))),
                status=str(item.get("event_status", "")),
                winner=item.get("event_winner"),
                raw=item,
            ))
        return matches

    def odds(self, target_date: date) -> dict[str, Any]:
        return self._get(
            "get_odds",
            date_start=target_date.isoformat(),
            date_stop=target_date.isoformat(),
        ) or {}

    def h2h(self, player_a_key: str, player_b_key: str) -> dict[str, Any]:
        return self._get("get_H2H", first_player_key=player_a_key, second_player_key=player_b_key) or {}
