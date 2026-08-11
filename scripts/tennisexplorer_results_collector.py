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

BASE_URLS = ("https://www.tennisexplorer.com", "https://noproxy.tennisexplorer.com")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
BRAZIL_TZ = timezone(timedelta(hours=-3))
UTC = timezone.utc
EXCLUDED = ("challenger", "chall.", "itf", "futures", "utr", "davis cup", "uk pro", "exhibition", "laver cup")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _player(cell: Tag | None) -> str:
    if not cell:
        return ""
    a = cell.find("a")
    text = _clean(a.get_text(" ", strip=True) if a else cell.get_text(" ", strip=True))
    return re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()


def _time(row: Tag) -> str | None:
    cell = row.select_one("td.first.time")
    if not cell:
        for td in row.find_all("td"):
            if "time" in {str(x).lower() for x in (td.get("class") or [])}:
                cell = td; break
    m = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", _clean(cell.get_text(" ", strip=True) if cell else ""))
    return m.group(0) if m else None


def _detail(row_a: Tag, row_b: Tag, base: str) -> str | None:
    for row in (row_a, row_b):
        for a in row.find_all("a", href=True):
            href = str(a.get("href") or "")
            if "match-detail" in href:
                return urljoin(base, href)
    return None


def _sets_won(row: Tag) -> int | None:
    cells = [c for c in row.find_all("td", recursive=False) if isinstance(c, Tag)]
    name_idx = next((i for i,c in enumerate(cells) if "t-name" in {str(x).lower() for x in (c.get("class") or [])}), None)
    if name_idx is None:
        return None
    for cell in cells[name_idx + 1:]:
        text = _clean(cell.get_text(" ", strip=True))
        # The S column on TennisExplorer is the first small integer after the player name.
        if re.fullmatch(r"[0-5]", text):
            return int(text)
    return None


def _avg_odds(row: Tag) -> tuple[float | None, float | None]:
    vals: list[float] = []
    for td in row.find_all("td"):
        cls = {str(x).lower() for x in (td.get("class") or [])}
        if not ({"course", "coursew"} & cls):
            continue
        m = re.search(r"\d+(?:[.,]\d+)?", _clean(td.get_text(" ", strip=True)))
        if not m:
            continue
        try:
            v = float(m.group(0).replace(",", "."))
        except ValueError:
            continue
        if v > 1:
            vals.append(v)
    return (vals[0], vals[1]) if len(vals) >= 2 else (None, None)


def _utc(target: date, hhmm: str) -> str:
    dt = datetime.strptime(f"{target.isoformat()} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=BRAZIL_TZ)
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_results(html: str, target: date, base: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    tables = [t for t in soup.find_all("table") if isinstance(t, Tag)]
    tables = [t for t in tables if "result" in {str(x).lower() for x in (t.get("class") or [])}] or tables
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for table in tables:
        rows = [r for r in (table.find("tbody") or table).find_all("tr") if isinstance(r, Tag)]
        tournament = ""
        i = 0
        while i < len(rows):
            row = rows[i]
            classes = {str(x).lower() for x in (row.get("class") or [])}
            if "head" in classes:
                cell = row.find("td", class_="t-name")
                tournament = _clean(cell.get_text(" ", strip=True) if cell else "")
                i += 1; continue
            if not tournament or any(x in tournament.casefold() for x in EXCLUDED):
                i += 1; continue
            cell = row.find("td", class_="t-name")
            hhmm = _time(row)
            if not cell or not hhmm:
                i += 1; continue
            j = i + 1
            opponent = None
            while j < len(rows):
                cand = rows[j]
                if "head" in {str(x).lower() for x in (cand.get("class") or [])}:
                    break
                if cand.find("td", class_="t-name"):
                    opponent = cand; break
                j += 1
            if opponent is None:
                i += 1; continue
            a = _player(cell); b = _player(opponent.find("td", class_="t-name"))
            sa = _sets_won(row); sb = _sets_won(opponent)
            if not a or not b or sa is None or sb is None or sa == sb:
                i = j + 1; continue
            link = _detail(row, opponent, base) or f"{base}/results/{target.isoformat()}/{tournament}/{a}/{b}"
            if link in seen:
                i = j + 1; continue
            seen.add(link)
            odd_a, odd_b = _avg_odds(row)
            market = []
            if odd_a and odd_b:
                market.append({"player_1": f"{odd_a:.3f}", "player_2": f"{odd_b:.3f}", "bookmaker_name": "TennisExplorer avg", "period": "FullTime", "submarket_name": "Home/Away", "source": "TennisExplorer results"})
            output.append({
                "match_date": _utc(target, hhmm), "home_team": a, "away_team": b,
                "league_name": f"ATP {tournament}", "match_link": link,
                "home_score": str(sa), "away_score": str(sb), "match_winner_market": market,
            })
            i = j + 1
    return output


def collect(target: date) -> tuple[list[dict[str, Any]], str]:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8"}
    params = {"type": "atp-single", "year": str(target.year), "month": f"{target.month:02d}", "day": f"{target.day:02d}"}
    errors = []
    for base in BASE_URLS:
        try:
            r = requests.get(f"{base}/results/", params=params, headers=headers, timeout=35)
            if r.status_code != 200:
                errors.append(f"{base}: HTTP {r.status_code}"); continue
            rows = parse_results(r.text, target, base)
            if rows:
                print(f"[TQE] TennisExplorer results {target}: {len(rows)} ATP finished matches", file=sys.stderr, flush=True)
                return rows, base
            errors.append(f"{base}: zero finished ATP rows")
        except requests.RequestException as exc:
            errors.append(f"{base}: {exc}")
    raise RuntimeError("; ".join(errors[-4:]) or "results collection failed")


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--date", required=True); p.add_argument("--output", required=True)
    args = p.parse_args(); target = datetime.strptime(args.date.replace("-", ""), "%Y%m%d").date()
    rows, source = collect(target)
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"source": source, "matches": len(rows), "output": str(out)}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
