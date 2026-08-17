from __future__ import annotations

import time
from datetime import date
from typing import Any

import requests

from tennis_quant.domain import Match, Player

BASE_URL = "https://api.api-tennis.com/tennis/"
ATP_SINGLES_EVENT_KEY = "265"


class ApiTennisProvider:
    """Thin API-Tennis adapter used only from the backend workflow."""

    def __init__(self, api_key: str, timeout: int = 45):
        if not api_key:
            raise ValueError("API_TENNIS_KEY is required")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.request_count = 0
        self.source_requests = 0
        self.live_source = "API-Tennis"
        self.current_context_date = date.today()

    def _get(self, method: str, **params: Any) -> Any:
        query = {"method": method, "APIkey": self.api_key, **params}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                self.request_count += 1
                self.source_requests = self.request_count
                response = self.session.get(BASE_URL, params=query, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if not payload.get("success"):
                    raise RuntimeError(f"API-Tennis error in {method}: {payload}")
                return payload.get("result")
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"API-Tennis request failed in {method}: {last_error}")

    @staticmethod
    def _to_match(item: dict[str, Any], fallback_date: str = "") -> Match:
        surface = (
            item.get("surface")
            or item.get("tournament_surface")
            or item.get("event_surface")
            or item.get("court_surface")
        )
        return Match(
            match_id=str(item.get("event_key", "")),
            date=str(item.get("event_date", fallback_date)),
            time=str(item.get("event_time", "")),
            tournament=str(item.get("tournament_name", item.get("league_name", "Unknown"))),
            event_type="ATP Singles",
            surface=str(surface).strip() if surface else None,
            player_a=Player(str(item.get("first_player_key", "")), str(item.get("event_first_player", "Player A"))),
            player_b=Player(str(item.get("second_player_key", "")), str(item.get("event_second_player", "Player B"))),
            status=str(item.get("event_status", "")),
            winner=item.get("event_winner"),
            raw=item,
        )

    def fixtures(self, target_date: date, event_type_key: str = ATP_SINGLES_EVENT_KEY) -> list[Match]:
        self.current_context_date = target_date
        return self.fixtures_range(target_date, target_date, event_type_key=event_type_key)

    def fixtures_range(
        self,
        start_date: date,
        end_date: date,
        event_type_key: str = ATP_SINGLES_EVENT_KEY,
        player_key: str | None = None,
    ) -> list[Match]:
        params: dict[str, Any] = {
            "date_start": start_date.isoformat(),
            "date_stop": end_date.isoformat(),
            "event_type_key": event_type_key,
            "timezone": "America/Sao_Paulo",
        }
        if player_key:
            params["player_key"] = player_key
        raw = self._get("get_fixtures", **params) or []
        matches: list[Match] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            match = self._to_match(item, start_date.isoformat())
            if match.match_id and match.player_a.key and match.player_b.key:
                matches.append(match)
        return matches

    def odds(self, target_date: date, event_type_key: str = ATP_SINGLES_EVENT_KEY) -> dict[str, Any]:
        self.current_context_date = target_date
        result = self._get(
            "get_odds",
            date_start=target_date.isoformat(),
            date_stop=target_date.isoformat(),
            event_type_key=event_type_key,
        ) or {}
        return result if isinstance(result, dict) else {}

    def h2h(self, player_a_key: str, player_b_key: str) -> dict[str, Any]:
        result = self._get("get_H2H", first_player_key=player_a_key, second_player_key=player_b_key) or {}
        return result if isinstance(result, dict) else {}

    def standings(self, event_type: str = "ATP") -> dict[str, dict[str, Any]]:
        rows = self._get("get_standings", event_type=event_type) or []
        output: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("player_key", ""))
            if key:
                output[key] = row
        return output

    def player_profile(self, player_key: str) -> dict[str, Any]:
        rows = self._get("get_players", player_key=player_key) or []
        if isinstance(rows, list) and rows:
            return rows[0] if isinstance(rows[0], dict) else {}
        if isinstance(rows, dict):
            return rows
        return {}

    def player_history(self, player_key: str, start_date: date, end_date: date) -> list[Match]:
        return self.fixtures_range(start_date, end_date, player_key=player_key)
