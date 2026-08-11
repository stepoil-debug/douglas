from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from scripts.tennisexplorer_collector import (
    BASE_URLS,
    BRAZIL_TZ,
    EXCLUDED_TOURNAMENT_TOKENS,
    USER_AGENT,
    _clean,
    _detail_link,
    _match_time,
    _odds_from_row,
    _player_name,
    _utc_match_date,
    enrich_bookmakers,
)


def _excluded(value: str) -> bool:
    lower = value.casefold()
    return any(token in lower for token in EXCLUDED_TOURNAMENT_TOKENS)


def discover_tournament_links(html: str, base_url: str, year: int) -> list[tuple[str, str]]:
    """Return ATP singles tournament URLs visible in a dated schedule/results page."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}
    for row in soup.find_all("tr"):
        if not isinstance(row, Tag):
            continue
        classes = {str(x).lower() for x in (row.get("class") or [])}
        if "head" not in classes:
            continue
        cell = row.find("td", class_="t-name")
        if not cell:
            continue
        label = _clean(cell.get_text(" ", strip=True))
        if not label or _excluded(label):
            continue
        for anchor in cell.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            normalized = href.casefold()
            if f"/{year}/" not in normalized or "/atp-men/" not in normalized:
                continue
            if any(x in normalized for x in ("qualification", "doubles")):
                continue
            found[urljoin(base_url, href)] = label
    return sorted(((name, url) for url, name in found.items()), key=lambda x: x[0].casefold())


def _row_calendar_date(row: Tag, year: int) -> date | None:
    # Tournament pages print dates as dd.mm. in the first/start cell.
    cells = row.find_all("td", recursive=False)
    text = _clean(cells[0].get_text(" ", strip=True) if cells else row.get_text(" ", strip=True))
    m = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(?!\d)", text)
    if not m:
        return None
    try:
        return date(year, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _tournament_name(soup: BeautifulSoup, fallback: str, year: int) -> str:
    if fallback:
        # Header labels sometimes contain country or court metadata. Keep the concise
        # label already discovered from the schedule page where possible.
        return fallback.strip()
    h1 = soup.find("h1")
    raw = _clean(h1.get_text(" ", strip=True) if h1 else "ATP")
    raw = re.sub(rf"\s+{year}\b.*$", "", raw).strip()
    return raw or "ATP"


def parse_tournament_page(
    html: str,
    target: date,
    base_url: str,
    tournament_name: str = "",
) -> list[dict[str, Any]]:
    """Parse only target-date pre-match rows from a TennisExplorer tournament page."""
    soup = BeautifulSoup(html, "html.parser")
    name = _tournament_name(soup, tournament_name, target.year)
    if _excluded(name):
        return []
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    tables = [t for t in soup.find_all("table") if isinstance(t, Tag)]
    result_tables = [t for t in tables if "result" in {str(x).lower() for x in (t.get("class") or [])}]
    for table in result_tables or tables:
        rows = [r for r in (table.find("tbody") or table).find_all("tr") if isinstance(r, Tag)]
        i = 0
        while i < len(rows):
            row = rows[i]
            row_date = _row_calendar_date(row, target.year)
            hhmm = _match_time(row)
            player_cell = row.find("td", class_="t-name")
            if row_date != target or not hhmm or not player_cell:
                i += 1
                continue

            j = i + 1
            opponent: Tag | None = None
            while j < len(rows):
                candidate = rows[j]
                # Another dated first-player row means the expected opponent row was
                # not present; do not accidentally pair different matches.
                if _row_calendar_date(candidate, target.year) is not None:
                    break
                if candidate.find("td", class_="t-name"):
                    opponent = candidate
                    break
                j += 1
            if opponent is None:
                i += 1
                continue

            first = _player_name(player_cell)
            second = _player_name(opponent.find("td", class_="t-name"))
            odd_a, odd_b = _odds_from_row(row)
            if not first or not second or odd_a is None or odd_b is None:
                i = j + 1
                continue

            detail = _detail_link(row, opponent, base_url)
            key = (hhmm, first.casefold(), second.casefold())
            if key in seen:
                i = j + 1
                continue
            seen.add(key)
            records.append({
                "match_date": _utc_match_date(target, hhmm),
                "home_team": first,
                "away_team": second,
                "league_name": f"ATP {name}",
                "match_link": detail or urljoin(base_url, f"/tournament/{target.isoformat()}/{first}/{second}"),
                "home_score": "",
                "away_score": "",
                "match_winner_market": [{
                    "player_1": f"{odd_a:.3f}",
                    "player_2": f"{odd_b:.3f}",
                    "bookmaker_name": "TennisExplorer avg",
                    "period": "FullTime",
                    "submarket_name": "Home/Away",
                    "source": "TennisExplorer tournament page",
                }],
            })
            i = j + 1
    return records


def _headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
    }


def _seed_params(day: date) -> dict[str, str]:
    return {
        "type": "atp-single",
        "year": str(day.year),
        "month": str(day.month),
        "day": str(day.day),
        "timezone": "-3",
    }


def collect(target: date) -> tuple[list[dict[str, Any]], str]:
    headers = _headers()
    seed = target - timedelta(days=1)
    errors: list[str] = []

    for base in BASE_URLS:
        links: dict[str, str] = {}
        # Today's matches/results are proven to be visible on the runner and expose
        # the links to the currently active ATP tournament pages.
        for endpoint in ("matches", "results"):
            try:
                response = requests.get(f"{base}/{endpoint}/", params=_seed_params(seed), headers=headers, timeout=30)
                if response.status_code != 200:
                    errors.append(f"seed {endpoint}: HTTP {response.status_code}")
                    continue
                for name, url in discover_tournament_links(response.text, base, target.year):
                    links[url] = name
            except requests.RequestException as exc:
                errors.append(f"seed {endpoint}: {exc}")

        if not links:
            errors.append(f"{base}: no active ATP tournament links")
            continue

        records: list[dict[str, Any]] = []
        for url, name in sorted(links.items()):
            try:
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    errors.append(f"{urlparse(url).path}: HTTP {response.status_code}")
                    continue
                rows = parse_tournament_page(response.text, target, base, name)
                records.extend(rows)
            except requests.RequestException as exc:
                errors.append(f"{urlparse(url).path}: {exc}")

        if records:
            unique: dict[tuple[str, str, str], dict[str, Any]] = {}
            for record in records:
                key = (record["match_date"], record["home_team"].casefold(), record["away_team"].casefold())
                unique[key] = record
            records = list(unique.values())
            enriched = enrich_bookmakers(records, headers)
            print(
                f"[TQE] Tournament-page D+1 fallback: {len(records)} ATP matches from "
                f"{len(links)} active tournaments; {enriched} bookmaker-enriched",
                file=sys.stderr,
                flush=True,
            )
            return records, f"{base}/active-tournaments"

    raise RuntimeError("; ".join(errors[-10:]) or "no D+1 matches published on active tournament pages")


def main() -> int:
    p = argparse.ArgumentParser(description="Collect D+1 ATP schedule from active TennisExplorer tournament pages")
    p.add_argument("--date", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    target = datetime.strptime(args.date.replace("-", ""), "%Y%m%d").date()
    try:
        rows, source = collect(target)
    except Exception as exc:
        print(f"[TQE] Tournament fallback unavailable: {exc}", file=sys.stderr, flush=True)
        return 42
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"source": source, "matches": len(rows), "output": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
