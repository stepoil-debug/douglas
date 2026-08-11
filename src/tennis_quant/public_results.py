from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from tennis_quant.domain import Match
from tennis_quant.providers.public_tennis import SAO_PAULO, _norm, _parse_utc, _score_winner, _stable_match_id


def finished_fixtures(provider: Any, root: Path, target_day: date) -> list[Match]:
    runtime = root / "data" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    output = runtime / f"results_tennis_{target_day.isoformat()}.json"
    if output.exists():
        output.unlink()
    cmd = [
        sys.executable,
        "scripts/tennisexplorer_results_collector.py",
        "--date", target_day.strftime("%Y%m%d"),
        "--output", str(output),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if completed.stdout:
        print(completed.stdout[-3000:], file=sys.stderr, flush=True)
    if completed.stderr:
        print(completed.stderr[-4000:], file=sys.stderr, flush=True)
    if completed.returncode != 0 or not output.exists():
        raise RuntimeError((completed.stderr or completed.stdout or "public results collector failed")[-1000:])
    records = json.loads(output.read_text(encoding="utf-8"))
    provider.sackmann.ensure_window(date(max(1968, target_day.year - 1), 1, 1), target_day)
    matches: list[Match] = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        league = str(record.get("league_name") or "")
        league_norm = _norm(league)
        if "atp" not in league_norm or any(x in league_norm for x in ("wta", "challenger", "itf", "doubles")):
            continue
        home_name = str(record.get("home_team") or "").strip()
        away_name = str(record.get("away_team") or "").strip()
        if not home_name or not away_name:
            continue
        player_a = provider.sackmann.resolve_player(home_name)
        player_b = provider.sackmann.resolve_player(away_name)
        winner = _score_winner(record)
        if not winner:
            continue
        kickoff = _parse_utc(record.get("match_date"))
        local = kickoff.astimezone(SAO_PAULO) if kickoff else None
        match_id = _stable_match_id(record)
        surface = provider.sackmann.surface_for_tournament(league, target_day.year)
        matches.append(Match(
            match_id=match_id,
            date=(local.date().isoformat() if local else target_day.isoformat()),
            time=(local.strftime("%H:%M") if local else ""),
            tournament=league or "ATP",
            event_type="ATP Singles",
            surface=surface,
            player_a=player_a,
            player_b=player_b,
            status="Finished",
            winner=winner,
            raw={
                "event_key": match_id,
                "event_date": (local.date().isoformat() if local else target_day.isoformat()),
                "event_final_result": f"{record.get('home_score')} - {record.get('away_score')}",
                "event_winner": winner,
                "first_player_key": player_a.key,
                "second_player_key": player_b.key,
                "source": "TennisExplorer results",
                "source_url": record.get("match_link"),
            },
        ))
    return matches
