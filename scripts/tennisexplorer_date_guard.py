from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _with_timezone(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["timezone"] = "-3"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _explicit_date(text: str, reference_date: date) -> date | None:
    patterns = (
        r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b",
        r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
    )
    match = re.search(patterns[0], text)
    if match:
        day, month, year = map(int, match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    match = re.search(patterns[1], text)
    if match:
        year, month, day = map(int, match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    # TennisExplorer can omit the year for dates close to the reference day.
    match = re.search(r"\b(\d{1,2})[./](\d{1,2})[.]?(?=\s|,)", text)
    if match:
        day, month = map(int, match.groups())
        years = (reference_date.year, reference_date.year + 1, reference_date.year - 1)
        candidates: list[date] = []
        for year in years:
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                pass
        if candidates:
            return min(candidates, key=lambda d: abs((d - reference_date).days))
    return None


def parse_detail_schedule(html: str, reference_date: date) -> tuple[date | None, str | None]:
    """Read the actual local date/time exposed on a TennisExplorer detail page."""
    soup = BeautifulSoup(html, "html.parser")
    chunks: list[str] = []
    for node in soup.find_all(["h1", "h2", "div", "span", "p", "td"], limit=500):
        text = _clean(node.get_text(" ", strip=True))
        if text and ":" in text:
            chunks.append(text)
    text = " | ".join(chunks)
    if not text:
        text = _clean(soup.get_text(" ", strip=True))

    time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    hhmm = None
    if time_match:
        hhmm = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"

    lower = text.casefold()
    actual_date: date | None = None
    # English is the normal public page, but keep Portuguese/Spanish variants too.
    if re.search(r"\b(today|hoje|hoy)\b", lower):
        actual_date = reference_date
    elif re.search(r"\b(tomorrow|amanhã|amanha|mañana|manana)\b", lower):
        actual_date = reference_date + timedelta(days=1)
    elif re.search(r"\b(yesterday|ontem|ayer)\b", lower):
        actual_date = reference_date - timedelta(days=1)
    else:
        actual_date = _explicit_date(text, reference_date)

    return actual_date, hhmm


def _to_utc_string(local_date: date, hhmm: str) -> str:
    local = datetime.strptime(f"{local_date.isoformat()} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=SAO_PAULO)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def verify_records(
    records: list[dict[str, Any]],
    target_date: date,
    *,
    reference_date: date | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Verify actual dates from detail pages and keep only the requested local date.

    This prevents a multi-day TennisExplorer page from being stamped wholesale with
    the requested D+1 date. Records whose detail date is unavailable are retained
    only when their existing local date already equals the target date.
    """
    reference_date = reference_date or datetime.now(SAO_PAULO).date()
    session = session or requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
    }

    kept: list[dict[str, Any]] = []
    verified = 0
    dropped_other_date = 0
    unavailable = 0

    for record in records:
        if not isinstance(record, dict):
            continue
        link = str(record.get("match_link") or "").strip()
        actual_date: date | None = None
        actual_time: str | None = None
        if "match-detail" in link:
            try:
                response = session.get(_with_timezone(link), headers=headers, timeout=25)
                if response.status_code == 200:
                    actual_date, actual_time = parse_detail_schedule(response.text, reference_date)
                time.sleep(0.08)
            except requests.RequestException:
                pass

        if actual_date and actual_time:
            verified += 1
            record["schedule_verified_local_date"] = actual_date.isoformat()
            record["schedule_verified_local_time"] = actual_time
            record["schedule_date_verified"] = True
            record["match_date"] = _to_utc_string(actual_date, actual_time)
            record["time_confirmed"] = True
            if actual_date != target_date:
                dropped_other_date += 1
                continue
            kept.append(record)
            continue

        unavailable += 1
        # Conservative fallback: only retain a record when its already-stamped local
        # date is the requested date. The time guard may still mark its clock unknown.
        raw = str(record.get("match_date") or "").strip()
        parsed: datetime | None = None
        for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                pass
        local_date = parsed.astimezone(SAO_PAULO).date() if parsed else None
        if local_date == target_date:
            record["schedule_date_verified"] = False
            kept.append(record)

    records[:] = kept
    return {
        "status": "OK",
        "target_date": target_date.isoformat(),
        "records": len(kept),
        "verified": verified,
        "dropped_other_date": dropped_other_date,
        "detail_unavailable": unavailable,
    }


def guard_file(path: Path, target_date: date, reference_date: date | None = None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = next((payload.get(key) for key in ("data", "results", "matches") if isinstance(payload.get(key), list)), None)
        if rows is None:
            rows = [payload] if payload.get("home_team") else []
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("unsupported schedule payload")

    summary = verify_records(rows, target_date, reference_date=reference_date)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify TennisExplorer match dates using detail pages")
    parser.add_argument("--input", required=True)
    parser.add_argument("--date", required=True, help="Expected local date YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--reference-date", help="Override today's Sao Paulo date for deterministic tests")
    args = parser.parse_args()
    target = datetime.strptime(args.date.replace("-", ""), "%Y%m%d").date()
    reference = datetime.strptime(args.reference_date, "%Y-%m-%d").date() if args.reference_date else None
    try:
        summary = guard_file(Path(args.input), target, reference)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("records", 0) > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
