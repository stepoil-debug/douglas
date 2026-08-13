from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from scripts.tennisexplorer_collector import (
    BASE_URLS,
    USER_AGENT,
    _candidate_tables,
    _diagnostic,
    _parse_table,
    enrich_bookmakers,
)
from scripts.tennisexplorer_date_guard import verify_records
from scripts.tennisexplorer_sections import table_section_date


def parse_target_day(html: str, target: date, base_url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse only tables explicitly owned by target's visible date heading.

    TennisExplorer can serve several calendar dates on one HTML page and its query
    string is not a reliable filter. This parser follows the visible dd.mm.yyyy
    heading attached to each result table before creating any record.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = _candidate_tables(soup)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    explicit_tables = 0
    target_tables = 0
    skipped_other_day = 0
    uncertain_tables = 0

    for table in tables:
        section = table_section_date(table)
        if section is not None:
            explicit_tables += 1
            if section != target:
                skipped_other_day += 1
                continue
            target_tables += 1
            parse_day = section
        else:
            uncertain_tables += 1
            parse_day = target

        for record in _parse_table(table, parse_day, base_url):
            if section is not None:
                record["schedule_section_date"] = section.isoformat()
                record["schedule_date_verified"] = True
                record["schedule_verification_method"] = "VISIBLE_DATE_SECTION"
            key = (record["match_date"], record["home_team"], record["away_team"])
            if key not in seen:
                seen.add(key)
                records.append(record)

    # If the page exposes explicit calendar headings, never keep rows from tables
    # without an explicit heading. Mixing them back in would undo the safety rule.
    if explicit_tables:
        records = [r for r in records if r.get("schedule_verification_method") == "VISIBLE_DATE_SECTION"]
    elif records:
        # Legacy layout fallback. Verify the date from match-detail pages before the
        # rows can enter the board.
        verify_records(records, target)
        records = [r for r in records if r.get("schedule_date_verified") is True]

    return records, {
        "tables": len(tables),
        "explicit_tables": explicit_tables,
        "target_tables": target_tables,
        "skipped_other_day": skipped_other_day,
        "uncertain_tables": uncertain_tables,
        "records": len(records),
    }


def collect(target: date) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
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

    # /matches is the canonical schedule view. /results is only a schedule fallback
    # for pre-match rows that TennisExplorer sometimes leaves there around rollover.
    for endpoint in ("matches", "results"):
        for base in BASE_URLS:
            url = f"{base}/{endpoint}/"
            for params in param_variants:
                try:
                    response = requests.get(url, params=params, headers=headers, timeout=35)
                    if response.status_code != 200:
                        errors.append(f"{base}/{endpoint}: HTTP {response.status_code}")
                        continue
                    rows, summary = parse_target_day(response.text, target, base)
                    if not rows:
                        errors.append(f"{base}/{endpoint}: zero target rows ({_diagnostic(response.text)}; {summary})")
                        continue
                    enriched = enrich_bookmakers(rows, headers)
                    source = f"{base}/{endpoint}#visible-date-section"
                    summary["enriched"] = enriched
                    print(
                        f"[TQE] TennisExplorer V2 {target}: {len(rows)} ATP rows from explicit date section; "
                        f"{summary.get('skipped_other_day', 0)} other-day tables skipped; {enriched} enriched",
                        file=sys.stderr,
                        flush=True,
                    )
                    return rows, source, summary
                except Exception as exc:
                    errors.append(f"{base}/{endpoint}: {exc}")
    raise RuntimeError("; ".join(errors[-8:]) or "TennisExplorer V2 schedule collection failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect ATP schedule from explicit TennisExplorer date sections")
    parser.add_argument("--date", required=True, help="YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = datetime.strptime(args.date.replace("-", ""), "%Y%m%d").date()
    try:
        records, source, summary = collect(target)
    except Exception as exc:
        print(f"[TQE] TennisExplorer V2 unavailable: {exc}", file=sys.stderr, flush=True)
        return 42
    if not records:
        return 42
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"source": source, "matches": len(records), "summary": summary, "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
