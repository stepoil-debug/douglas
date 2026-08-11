from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

BASE_URLS = (
    "https://www.tennisexplorer.com",
    "https://noproxy.tennisexplorer.com",
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
BRAZIL_TZ = timezone(timedelta(hours=-3))
UTC = timezone.utc

EXCLUDED_TOURNAMENT_TOKENS = (
    "challenger",
    "chall.",
    "itf",
    "futures",
    "utr",
    "davis cup",
    "uk pro",
    "exhibition",
    "laver cup",
)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()


def _player_name(cell: Tag | None) -> str:
    if cell is None:
        return ""
    anchor = cell.find("a")
    raw = _clean(anchor.get_text(" ", strip=True) if anchor else cell.get_text(" ", strip=True))
    return re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()


def _float(text: Any) -> float | None:
    raw = _clean(text).replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        value = float(match.group(0))
    except ValueError:
        return None
    return value if value > 1.0 else None


def _odds_from_row(row: Tag) -> tuple[float | None, float | None]:
    values: list[float] = []
    for cell in row.find_all("td"):
        classes = {str(x).lower() for x in (cell.get("class") or [])}
        if not ({"course", "coursew"} & classes):
            continue
        value = _float(cell.get_text(" ", strip=True))
        if value is not None:
            values.append(value)
    if len(values) >= 2:
        return values[0], values[1]
    return None, None


def _match_time(row: Tag) -> str | None:
    cell = row.select_one("td.first.time")
    if not cell:
        for td in row.find_all("td"):
            classes = {str(x).lower() for x in (td.get("class") or [])}
            if "time" in classes:
                cell = td
                break
    raw = _clean(cell.get_text(" ", strip=True) if cell else "")
    match = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", raw)
    return match.group(0) if match else None


def _detail_link(row_a: Tag, row_b: Tag, base_url: str) -> str | None:
    for row in (row_a, row_b):
        for anchor in row.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if "match-detail" in href:
                return urljoin(base_url, href)
    return None


def _utc_match_date(target: date, hhmm: str) -> str:
    local = datetime.strptime(f"{target.isoformat()} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=BRAZIL_TZ)
    return local.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _is_target_tournament(name: str) -> bool:
    lower = name.casefold()
    return bool(name) and not any(token in lower for token in EXCLUDED_TOURNAMENT_TOKENS)


def _candidate_tables(soup: BeautifulSoup) -> list[Tag]:
    tables = [t for t in soup.find_all("table") if isinstance(t, Tag)]
    result = [t for t in tables if "result" in {str(x).lower() for x in (t.get("class") or [])}]
    return result or tables


def _parse_table(table: Tag, target: date, base_url: str) -> list[dict[str, Any]]:
    tbody = table.find("tbody") or table
    # recursive=True is deliberate. Some current renderings wrap rows while older ones did not.
    rows = [row for row in tbody.find_all("tr") if isinstance(row, Tag)]
    records: list[dict[str, Any]] = []
    tournament = ""
    index = 0
    while index < len(rows):
        row = rows[index]
        classes = {str(x).lower() for x in (row.get("class") or [])}
        if "head" in classes:
            name_cell = row.find("td", class_="t-name")
            tournament = _clean(name_cell.get_text(" ", strip=True) if name_cell else "")
            index += 1
            continue

        name_cell = row.find("td", class_="t-name")
        hhmm = _match_time(row)
        if not name_cell or not hhmm or not _is_target_tournament(tournament):
            index += 1
            continue

        opponent_row: Tag | None = None
        look = index + 1
        while look < len(rows):
            candidate = rows[look]
            candidate_classes = {str(x).lower() for x in (candidate.get("class") or [])}
            if "head" in candidate_classes:
                break
            if candidate.find("td", class_="t-name"):
                opponent_row = candidate
                break
            look += 1
        if opponent_row is None:
            index += 1
            continue

        first = _player_name(name_cell)
        second = _player_name(opponent_row.find("td", class_="t-name"))
        home_odd, away_odd = _odds_from_row(row)
        if not first or not second or home_odd is None or away_odd is None:
            index = look + 1
            continue

        detail = _detail_link(row, opponent_row, base_url)
        records.append({
            "match_date": _utc_match_date(target, hhmm),
            "home_team": first,
            "away_team": second,
            "league_name": f"ATP {tournament}",
            "match_link": detail or f"{base_url}/matches/{target.isoformat()}/{tournament}/{first}/{second}",
            "home_score": "",
            "away_score": "",
            "match_winner_market": [{
                "player_1": f"{home_odd:.3f}",
                "player_2": f"{away_odd:.3f}",
                "bookmaker_name": "TennisExplorer avg",
                "period": "FullTime",
                "submarket_name": "Home/Away",
                "source": "TennisExplorer schedule",
            }],
        })
        index = look + 1
    return records


def parse_matches(html: str, target: date, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    tables = _candidate_tables(soup)
    if not tables:
        raise RuntimeError("TennisExplorer returned no tables")
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for table in tables:
        for record in _parse_table(table, target, base_url):
            key = (record["match_date"], record["home_team"], record["away_team"])
            if key not in seen:
                seen.add(key)
                records.append(record)
    return records


def _diagnostic(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    title = _clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    tables = len(soup.find_all("table"))
    result_tables = len(soup.find_all("table", class_="result"))
    trs = len(soup.find_all("tr"))
    text = _clean(soup.get_text(" ", strip=True))[:450]
    return f"title={title!r}, bytes={len(html)}, tables={tables}, result_tables={result_tables}, tr={trs}, sample={text!r}"


def collect(target: date) -> tuple[list[dict[str, Any]], str]:
    param_variants = [
        {"type": "atp-single", "year": str(target.year), "month": str(target.month), "day": str(target.day), "timezone": "-3"},
        {"type": "atp-single", "year": str(target.year), "month": f"{target.month:02d}", "day": f"{target.day:02d}", "timezone": "-3"},
    ]
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
    }
    errors: list[str] = []
    for base in BASE_URLS:
        url = f"{base}/matches/"
        for params in param_variants:
            try:
                response = requests.get(url, params=params, headers=headers, timeout=35)
                if response.status_code != 200:
                    errors.append(f"{base}: HTTP {response.status_code}")
                    continue
                rows = parse_matches(response.text, target, base)
                if not rows:
                    diag = _diagnostic(response.text)
                    errors.append(f"{base}: zero parsed matches ({diag})")
                    print(f"[TQE] TennisExplorer zero rows: {diag}", file=sys.stderr, flush=True)
                    continue
                print(f"[TQE] TennisExplorer source {base}: {len(rows)} ATP matches with H/A odds", file=sys.stderr, flush=True)
                return rows, base
            except Exception as exc:
                errors.append(f"{base}: {exc}")
    raise RuntimeError("; ".join(errors[-6:]) or "TennisExplorer collection failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect ATP Match Winner odds from TennisExplorer HTML")
    parser.add_argument("--date", required=True, help="YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = args.date.replace("-", "")
    target = datetime.strptime(raw, "%Y%m%d").date()
    records, source = collect(target)
    if not records:
        print("[TQE] TennisExplorer returned zero records", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"source": source, "matches": len(records), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
