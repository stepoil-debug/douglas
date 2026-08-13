from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tennis_quant.config import ROOT
from tennis_quant.providers.public_tennis import SAO_PAULO, _parse_utc, _record_live_source, _stable_match_id
from tennis_quant.sequence_sync import update_all_sequence_schedules


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=240)


def _load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "matches"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        if payload.get("home_team"):
            return [payload]
    return []


def _fixture(record: dict[str, Any], fallback_date: date) -> Any | None:
    kickoff = _parse_utc(record.get("match_date"))
    if kickoff is None:
        return None
    local = kickoff.astimezone(SAO_PAULO)
    return SimpleNamespace(
        match_id=_stable_match_id(record),
        date=local.date().isoformat(),
        time=local.strftime("%H:%M"),
        raw={
            "source": _record_live_source(record),
            "source_url": record.get("match_link"),
            "schedule_verified_local_date": record.get("schedule_verified_local_date"),
            "schedule_verified_local_time": record.get("schedule_verified_local_time"),
        },
    )


def collect_verified_day(target: date, operational_day: date) -> tuple[list[Any], dict[str, Any]]:
    runtime = ROOT / "data" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    output = runtime / f"sequence_schedule_{target.isoformat()}.json"
    if output.exists():
        output.unlink()

    collector = _run([
        sys.executable,
        "scripts/tennisexplorer_collector.py",
        "--date", target.isoformat(),
        "--output", str(output),
    ])
    if collector.returncode != 0 or not output.exists():
        return [], {
            "date": target.isoformat(),
            "status": "COLLECTOR_FAILED",
            "error": (collector.stderr or collector.stdout or "collector failed")[-700:],
        }

    date_guard = _run([
        sys.executable,
        "scripts/tennisexplorer_date_guard.py",
        "--input", str(output),
        "--date", target.isoformat(),
        "--reference-date", operational_day.isoformat(),
    ])
    if date_guard.returncode not in {0, 3}:
        return [], {
            "date": target.isoformat(),
            "status": "DATE_GUARD_FAILED",
            "error": (date_guard.stderr or date_guard.stdout or "date guard failed")[-700:],
        }

    time_guard = _run([
        sys.executable,
        "scripts/schedule_time_guard.py",
        "--input", str(output),
    ])
    if time_guard.returncode != 0:
        return [], {
            "date": target.isoformat(),
            "status": "TIME_GUARD_FAILED",
            "error": (time_guard.stderr or time_guard.stdout or "time guard failed")[-700:],
        }

    rows = _load_rows(output)
    fixtures = [fixture for record in rows if (fixture := _fixture(record, target)) is not None]
    detail = {}
    try:
        detail = json.loads((date_guard.stdout or "{}").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        pass
    return fixtures, {
        "date": target.isoformat(),
        "status": "OK",
        "fixtures": len(fixtures),
        "verified": detail.get("verified"),
        "dropped_other_date": detail.get("dropped_other_date"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh actual schedule metadata for frozen InvestBet sequences")
    parser.add_argument("--date", required=True, help="Operational date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=2, help="How many consecutive dates to inspect")
    args = parser.parse_args()
    operational_day = date.fromisoformat(args.date)

    fixtures: list[Any] = []
    days: list[dict[str, Any]] = []
    for offset in range(max(1, args.days)):
        target = operational_day + timedelta(days=offset)
        found, summary = collect_verified_day(target, operational_day)
        fixtures.extend(found)
        days.append(summary)

    sync = update_all_sequence_schedules(ROOT, fixtures)
    print(json.dumps({
        "operational_date": operational_day.isoformat(),
        "days": days,
        "schedule_sync": sync,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
