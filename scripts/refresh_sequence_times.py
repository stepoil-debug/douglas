from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tennis_quant.config import ROOT
from tennis_quant.providers.public_tennis import SAO_PAULO, _parse_utc, _record_live_source, _stable_match_id
from tennis_quant.sequence_sync import update_all_sequence_schedules


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=300)


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


def _fixture(record: dict[str, Any]) -> Any | None:
    kickoff = _parse_utc(record.get("match_date"))
    if kickoff is None:
        return None
    local = kickoff.astimezone(SAO_PAULO)
    return SimpleNamespace(
        match_id=_stable_match_id(record),
        date=local.date().isoformat(),
        time=local.strftime("%H:%M"),
        player_a=SimpleNamespace(key="", name=str(record.get("home_team") or "").strip()),
        player_b=SimpleNamespace(key="", name=str(record.get("away_team") or "").strip()),
        raw={
            "source": _record_live_source(record),
            "source_url": record.get("match_link"),
            "schedule_section_date": record.get("schedule_section_date"),
            "schedule_verification_method": record.get("schedule_verification_method"),
        },
    )


def _guard(output: Path) -> tuple[bool, str]:
    completed = _run([sys.executable, "scripts/schedule_time_guard.py", "--input", str(output)])
    return completed.returncode == 0, (completed.stdout or completed.stderr or "").strip()


def _collect_with(command: list[str], output: Path) -> tuple[list[Any], str, str]:
    if output.exists():
        output.unlink()
    completed = _run(command)
    if completed.returncode != 0 or not output.exists():
        return [], "FAILED", (completed.stderr or completed.stdout or "collector failed")[-900:]
    ok, guard_log = _guard(output)
    if not ok:
        return [], "GUARD_FAILED", guard_log[-900:]
    rows = _load_rows(output)
    fixtures = [fixture for row in rows if (fixture := _fixture(row)) is not None]
    return fixtures, "OK", guard_log[-900:]


def collect_verified_day(target: date) -> tuple[list[Any], dict[str, Any]]:
    runtime = ROOT / "data" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    output = runtime / f"sequence_schedule_{target.isoformat()}.json"

    # Primary: the general TennisExplorer page visibly groups matches by calendar
    # date. V2 follows that heading instead of trusting the URL query date, which is
    # exactly what we need after a frozen game is moved to another day.
    fixtures, status, detail = _collect_with([
        sys.executable,
        "scripts/tennisexplorer_schedule_collector_v2.py",
        "--date", target.isoformat(),
        "--output", str(output),
    ], output)
    source = "VISIBLE_DATE_SECTION"

    # Fallback for a layout/source outage: tournament pages have explicit dated rows.
    if not fixtures:
        fixtures, status, detail = _collect_with([
            sys.executable,
            "scripts/tennisexplorer_tournament_fallback.py",
            "--date", target.isoformat(),
            "--output", str(output),
        ], output)
        source = "TOURNAMENT_PAGE"

    pairs = [{
        "a": getattr(f.player_a, "name", ""),
        "b": getattr(f.player_b, "name", ""),
        "date": f.date,
        "time": f.time,
        "match_id": f.match_id,
    } for f in fixtures[:60]]
    return fixtures, {
        "date": target.isoformat(),
        "status": status if fixtures else "NO_VERIFIED_FIXTURES",
        "source": source,
        "fixtures": len(fixtures),
        "pairs": pairs,
        "detail": detail,
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
        found, summary = collect_verified_day(target)
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
