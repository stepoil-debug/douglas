from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://v3.football.api-sports.io"


class ApiFootballError(RuntimeError):
    pass


@dataclass
class ApiFootballClient:
    api_key: str
    timeout: int = 25
    min_interval_seconds: float = 0.35

    def __post_init__(self) -> None:
        self.api_key = (self.api_key or "").strip()
        if not self.api_key:
            raise ApiFootballError("API_FOOTBALL_KEY is not configured")
        self._last_request_at = 0.0
        self.request_count = 0

    @classmethod
    def from_env(cls) -> "ApiFootballClient":
        return cls(os.getenv("API_FOOTBALL_KEY", ""))

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        url = f"{API_BASE}{endpoint}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "x-apisports-key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "InvestBet-Football/1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ApiFootballError(f"API request failed for {endpoint}: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()
            self.request_count += 1

        errors = payload.get("errors")
        if errors:
            raise ApiFootballError(f"API-Football returned errors for {endpoint}: {errors}")
        return payload

    def fixtures_by_date(self, date: str, timezone: str = "America/Sao_Paulo") -> list[dict[str, Any]]:
        return list(self._get("/fixtures", {"date": date, "timezone": timezone}).get("response") or [])

    def odds_for_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        return list(self._get("/odds", {"fixture": fixture_id}).get("response") or [])

    def prediction_for_fixture(self, fixture_id: int) -> dict[str, Any] | None:
        rows = list(self._get("/predictions", {"fixture": fixture_id}).get("response") or [])
        return rows[0] if rows else None

    def head_to_head(self, home_team_id: int, away_team_id: int, last: int = 5) -> list[dict[str, Any]]:
        return list(
            self._get(
                "/fixtures/headtohead",
                {"h2h": f"{home_team_id}-{away_team_id}", "last": max(1, min(last, 20))},
            ).get("response")
            or []
        )


def _float_odd(value: Any) -> float | None:
    try:
        odd = float(value)
    except (TypeError, ValueError):
        return None
    return odd if odd > 1.0 else None


def extract_match_winner_odds(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return best available 1X2 prices across the bookmaker response."""
    best = {"home": None, "draw": None, "away": None}
    books: dict[str, dict[str, float]] = {}

    for row in rows:
        for bookmaker in row.get("bookmakers") or []:
            book_name = str(bookmaker.get("name") or "Bookmaker")
            for bet in bookmaker.get("bets") or []:
                bet_name = str(bet.get("name") or "").strip().lower()
                if bet_name not in {"match winner", "1x2", "winner"}:
                    continue
                current: dict[str, float] = {}
                for item in bet.get("values") or []:
                    label = str(item.get("value") or "").strip().lower()
                    odd = _float_odd(item.get("odd"))
                    if odd is None:
                        continue
                    key = None
                    if label in {"home", "1"}:
                        key = "home"
                    elif label in {"draw", "x"}:
                        key = "draw"
                    elif label in {"away", "2"}:
                        key = "away"
                    if key:
                        current[key] = odd
                        if best[key] is None or odd > best[key]:
                            best[key] = odd
                if current:
                    books[book_name] = current

    if not any(best.values()):
        return None
    return {"best": best, "bookmakers": books}
