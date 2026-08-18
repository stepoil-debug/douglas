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
    timeout: int = 30
    min_interval_seconds: float = 0.35

    def __post_init__(self) -> None:
        self.api_key = (self.api_key or "").strip()
        if not self.api_key:
            raise ApiFootballError("API_FOOTBALL_KEY is not configured")
        self._last_request_at = 0.0
        self.request_count = 0
        self.remaining_requests: int | None = None

    @classmethod
    def from_env(cls) -> "ApiFootballClient":
        key = (
            os.getenv("API_FOOTBALL_KEY", "").strip()
            or os.getenv("API_SPORTS_KEY", "").strip()
            or os.getenv("FOOTBALL_API_KEY", "").strip()
            or os.getenv("APISPORTS_KEY", "").strip()
        )
        return cls(key)

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
                "User-Agent": "InvestBet-Football/2.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw_remaining = response.headers.get("x-ratelimit-requests-remaining")
                if raw_remaining and raw_remaining.isdigit():
                    self.remaining_requests = int(raw_remaining)
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ApiFootballError(f"API request failed for {endpoint}: {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()
            self.request_count += 1

        errors = payload.get("errors")
        if isinstance(errors, dict) and errors:
            raise ApiFootballError(f"API-Football returned errors for {endpoint}: {errors}")
        if isinstance(errors, list) and errors:
            raise ApiFootballError(f"API-Football returned errors for {endpoint}: {errors}")
        return payload

    def fixtures_by_date(self, date: str, timezone: str = "America/Sao_Paulo") -> list[dict[str, Any]]:
        return list(self._get("/fixtures", {"date": date, "timezone": timezone}).get("response") or [])

    def odds_for_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        return list(self._get("/odds", {"fixture": fixture_id}).get("response") or [])

    def odds_by_date(self, date: str, max_pages: int = 8) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while page <= max(1, max_pages):
            payload = self._get("/odds", {"date": date, "page": page})
            rows.extend(list(payload.get("response") or []))
            paging = payload.get("paging") or {}
            total = int(paging.get("total") or 1)
            if page >= total:
                break
            page += 1
        return rows

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


def float_odd(value: Any) -> float | None:
    try:
        odd = float(value)
    except (TypeError, ValueError):
        return None
    return odd if odd > 1.0 else None


def fixture_id_from_odds(row: dict[str, Any]) -> int | None:
    fixture = row.get("fixture") or {}
    try:
        value = int(fixture.get("id"))
    except (TypeError, ValueError):
        return None
    return value or None


def market_prices(row: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten all pre-match markets for one fixture, keeping the best quoted price per market/selection."""
    if not row:
        return []
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for bookmaker in row.get("bookmakers") or []:
        bookmaker_name = str(bookmaker.get("name") or "Bookmaker").strip()
        for bet in bookmaker.get("bets") or []:
            market = str(bet.get("name") or "").strip()
            if not market:
                continue
            for item in bet.get("values") or []:
                selection = str(item.get("value") or "").strip()
                odd = float_odd(item.get("odd"))
                if not selection or odd is None:
                    continue
                key = (market.casefold(), selection.casefold())
                current = best.get(key)
                if current is None or odd > float(current["odd"]):
                    best[key] = {
                        "market": market,
                        "selection": selection,
                        "odd": round(odd, 3),
                        "bookmaker": bookmaker_name,
                    }
    return list(best.values())


def extract_match_winner_odds(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
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
                    odd = float_odd(item.get("odd"))
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
