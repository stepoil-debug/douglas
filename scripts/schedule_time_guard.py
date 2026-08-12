from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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


def _local_clock(record: dict[str, Any]) -> str | None:
    dt = _parse_utc(record.get("match_date"))
    if not dt:
        return None
    return dt.astimezone(SAO_PAULO).strftime("%H:%M")


def mark_unconfirmed_placeholder_times(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Remove highly suspicious repeated schedule times before model selection.

    Public tennis pages sometimes publish the next day's pairings and prices before
    publishing the actual court schedule. In that state many or all matches can
    receive the same placeholder clock (the observed case is 12:00 BRT). Treating
    that value as official breaks sequential-entry planning, so suspicious clocks
    are preserved only as diagnostics and the operational match_date is blanked.

    The rule is deliberately conservative: it works per tournament and requires a
    large repeated block. A normal group of a few simultaneous court starts is not
    touched.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if isinstance(record, dict):
            groups[str(record.get("league_name") or "ATP")].append(record)

    flagged = 0
    details: list[dict[str, Any]] = []
    for league, rows in groups.items():
        clocks = [_local_clock(row) for row in rows]
        usable = [clock for clock in clocks if clock]
        if not usable:
            continue
        counts = Counter(usable)
        dominant, count = counts.most_common(1)[0]
        share = count / max(1, len(usable))

        # Strong generic rule for a large board, plus a slightly smaller threshold
        # for common placeholder clocks seen on public schedule pages.
        suspicious = (
            (count >= 10 and share >= 0.70)
            or (dominant in {"12:00", "00:00"} and count >= 6 and share >= 0.80)
        )
        if not suspicious:
            continue

        league_flagged = 0
        for row in rows:
            if _local_clock(row) != dominant:
                row.setdefault("time_confirmed", True)
                continue
            original = str(row.get("match_date") or "")
            row["reported_match_date"] = original
            row["reported_local_time"] = dominant
            row["time_confirmed"] = False
            row["match_date"] = ""
            league_flagged += 1
            flagged += 1
        details.append({
            "league": league,
            "clock": dominant,
            "count": league_flagged,
            "share": round(share, 4),
        })

    for record in records:
        if isinstance(record, dict):
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

    summary = mark_unconfirmed_placeholder_times(rows)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard public tennis schedules against placeholder start times")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    path = Path(args.input)
    try:
        summary = guard_file(path)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "OK", **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
