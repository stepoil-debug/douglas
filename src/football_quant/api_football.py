from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from statistics import median
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://v3.football.api-sports.io"


class ApiFootballError(RuntimeError):
    pass


@dataclass
class ApiFootballClient:
    api_key: str
    timeout: int = 30
    min_interval_seconds: float = 6.2

    def __post_init__(self) -> None:
        self.api_key = (self.api_key or "").strip()
        if not self.api_key:
            raise ApiFootballError("API_FOOTBALL_KEY is not configured")
        override = os.getenv("API_FOOTBALL_MIN_INTERVAL", "").strip()
        if override:
            try:
                self.min_interval_seconds = max(0.2, float(override))
            except ValueError:
                pass
        self._last_request_at = 0.0
        self.request_count = 0
        self.remaining_requests: int | None = None
        self.minute_limit: int | None = None
        self.minute_remaining: int | None = None

    @classmethod
    def from_env(cls) -> "ApiFootballClient":
        key = (
            os.getenv("API_FOOTBALL_KEY", "").strip()
            or os.getenv("API_SPORTS_KEY", "").strip()
            or os.getenv("FOOTBALL_API_KEY", "").strip()
            or os.getenv("APISPORTS_KEY", "").strip()
        )
        return cls(key)

    def _respect_interval(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)

    def _read_headers(self, response: Any) -> None:
        daily_remaining = response.headers.get("x-ratelimit-requests-remaining")
        minute_limit = response.headers.get("X-RateLimit-Limit")
        minute_remaining = response.headers.get("X-RateLimit-Remaining")
        if daily_remaining and daily_remaining.isdigit():
            self.remaining_requests = int(daily_remaining)
        if minute_limit and minute_limit.isdigit():
            self.minute_limit = int(minute_limit)
        if minute_remaining and minute_remaining.isdigit():
            self.minute_remaining = int(minute_remaining)

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_BASE}{endpoint}?{urlencode(params)}"
        last_error: Exception | None = None
        for attempt in range(3):
            self._respect_interval()
            request = Request(
                url,
                headers={
                    "x-apisports-key": self.api_key,
                    "Accept": "application/json",
                    "User-Agent": "InvestBet-Football/2.2",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    self._read_headers(response)
                    payload = json.loads(response.read().decode("utf-8"))
                self._last_request_at = time.monotonic()
                self.request_count += 1
                errors = payload.get("errors")
                if isinstance(errors, dict) and errors:
                    if "rateLimit" in errors and attempt < 2:
                        time.sleep(12 * (attempt + 1))
                        continue
                    raise ApiFootballError(f"API-Football returned errors for {endpoint}: {errors}")
                if isinstance(errors, list) and errors:
                    raise ApiFootballError(f"API-Football returned errors for {endpoint}: {errors}")
                return payload
            except HTTPError as exc:
                self._last_request_at = time.monotonic()
                self.request_count += 1
                last_error = exc
                if exc.code == 429 and attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
                raise ApiFootballError(f"API request failed for {endpoint}: HTTP {exc.code}") from exc
            except ApiFootballError:
                raise
            except Exception as exc:
                self._last_request_at = time.monotonic()
                self.request_count += 1
                last_error = exc
                if attempt < 2:
                    time.sleep(4 * (attempt + 1))
                    continue
                break
        raise ApiFootballError(f"API request failed for {endpoint}: {last_error}") from last_error

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
    """Flatten markets and keep every bookmaker quote plus consensus price.

    `odd` is the best available price, while `consensus_odd` is the median quote.
    `quotes` lets the ticket builder ensure every leg in a multiple exists at the
    same bookmaker instead of multiplying prices from different books.
    """
    if not row:
        return []
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
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
                bucket = buckets.setdefault(
                    key,
                    {"market": market, "selection": selection, "quotes": {}},
                )
                previous = bucket["quotes"].get(bookmaker_name)
                if previous is None or odd > float(previous):
                    bucket["quotes"][bookmaker_name] = round(odd, 3)

    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        quotes: dict[str, float] = bucket["quotes"]
        if not quotes:
            continue
        best_book, best_odd = max(quotes.items(), key=lambda item: float(item[1]))
        values = [float(value) for value in quotes.values()]
        result.append(
            {
                "market": bucket["market"],
                "selection": bucket["selection"],
                "odd": round(float(best_odd), 3),
                "bookmaker": best_book,
                "consensus_odd": round(float(median(values)), 3),
                "bookmaker_count": len(values),
                "quotes": quotes,
            }
        )
    return result


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
