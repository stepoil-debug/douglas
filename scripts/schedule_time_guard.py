from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from scripts.tennisexplorer_date_guard import verify_records
except ModuleNotFoundError:  # direct execution
    from tennisexplorer_date_guard import verify_records

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _local_date(record: dict[str, Any]) -> date | None:
    dt = _parse_utc(record.get("match_date"))
    return dt.astimezone(SAO_PAULO).date() if dt else None


def _local_clock(record: dict[str, Any]) -> str | None:
    dt = _parse_utc(record.get("match_date"))
    return dt.astimezone(SAO_PAULO).strftime("%H:%M") if dt else None


def _expected_date(records: list[dict[str, Any]]) -> date | None:
    counts: Counter[date] = Counter()
    for row in records:
        d = _local_date(row)
        if d:
            counts[d] += 1
    return counts.most_common(1)[0][0] if counts else None


def _explicit_time_verified(record: dict[str, Any]) -> bool:
    # A time read from an individual match-detail page is authoritative here. A
    # visible dd.mm.yyyy section verifies the DATE only; the table clock can still
    # be a mass placeholder such as 12:00 before the order of play is published.
    return bool(record.get("schedule_verified_local_time"))


def mark_unconfirmed_placeholder_times(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Reject suspicious repeated clocks while preserving the verified date.

    Public tennis pages can publish pairings for the next day before assigning court
    times. In that state an entire tournament block may receive the same clock. We
    keep the explicit calendar date, mark only the time as pending and blank the
    synthetic timestamp so downstream code cannot mistake it for a confirmed start.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if isinstance(record, dict):
            groups[str(record.get("league_name") or "ATP")].append(record)

    flagged = 0
    details: list[dict[str, Any]] = []
    for league, rows in groups.items():
        candidates = [row for row in rows if not _explicit_time_verified(row)]
        clocks = [_local_clock(row) for row in candidates]
        usable = [clock for clock in clocks if clock]
        if not usable:
            continue
        counts = Counter(usable)
        dominant, count = counts.most_common(1)[0]
        share = count / max(1, len(usable))
        suspicious = (
            (count >= 10 and share >= 0.70)
            or (dominant in {"12:00", "00:00"} and count >= 6 and share >= 0.80)
        )
        if not suspicious:
            continue

        league_flagged = 0
        for row in candidates:
            if _local_clock(row) != dominant:
                row.setdefault("time_confirmed", True)
                continue
            original = str(row.get("match_date") or "")
            local_day = _local_date(row)
            row["reported_match_date"] = original
            row["reported_local_time"] = dominant
            row["time_confirmed"] = False
            # Preserve the calendar day separately before removing the untrusted
            # combined timestamp. Visible-date collectors normally already provide
            # schedule_section_date; this also covers legacy sources.
            if local_day and not row.get("schedule_section_date"):
                row["schedule_section_date"] = local_day.isoformat()
            row["match_date"] = ""
            league_flagged += 1
            flagged += 1
        details.append({"league": league, "clock": dominant, "count": league_flagged, "share": round(share, 4)})

    for record in records:
        if not isinstance(record, dict):
            continue
        if _explicit_time_verified(record):
            record["time_confirmed"] = True
        else:
            record.setdefault("time_confirmed", bool(record.get("match_date")))

    return {"flagged": flagged, "groups": details, "records": len(records)}


def guard_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = next((payload.get(key) for key in ("data", "results", "matches") if isinstance(payload.get(key), list)), None)
        if rows is None:
            rows = [payload] if payload.get("home_team") else []
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("unsupported schedule payload")

    expected = _expected_date(rows)
    date_summary: dict[str, Any] = {"status": "SKIPPED", "reason": "NO_EXPECTED_DATE"}
    if expected and rows and any("match-detail" in str(row.get("match_link") or "") for row in rows):
        # Skip a second network pass when the collector already verified the DATE.
        if all(row.get("schedule_date_verified") is True for row in rows):
            date_summary = {"status": "ALREADY_VERIFIED", "records": len(rows), "target_date": expected.isoformat()}
        else:
            date_summary = verify_records(rows, expected)

    time_summary = mark_unconfirmed_placeholder_times(rows)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**time_summary, "expected_date": expected.isoformat() if expected else None, "date_guard": date_summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard tennis schedules against wrong dates and placeholder times")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        summary = guard_file(Path(args.input))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "OK", **summary}, ensure_ascii=False))
    return 0 if summary.get("records", 0) > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
