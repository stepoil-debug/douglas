from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .analyzer import TOP_LIMIT, analyze_fixture, eligible_fixtures, rank_analyses
from .api_football import ApiFootballClient, ApiFootballError

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"
HISTORY = ROOT / "data" / "football" / "history"


def now() -> datetime:
    return datetime.now(TZ)


def dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def status(state: str, **extra: Any) -> None:
    payload = {
        "sport": "football",
        "status": state,
        "updated_at": now().isoformat(),
        **extra,
    }
    dump(DASHBOARD / "run_status.json", payload)


def historical_summary() -> dict[str, Any]:
    resolved = hits = misses = 0
    if not HISTORY.exists():
        return {"resolved": 0, "hits": 0, "misses": 0, "accuracy": None}
    for path in HISTORY.glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for match in row.get("approved") or []:
            match_status = str(match.get("status") or "").upper()
            if match_status in {"HIT", "GREEN"}:
                resolved += 1
                hits += 1
            elif match_status in {"MISS", "RED"}:
                resolved += 1
                misses += 1
    return {
        "resolved": resolved,
        "hits": hits,
        "misses": misses,
        "accuracy": (hits / resolved) if resolved else None,
    }


def run(target_date: str, max_candidates: int) -> int:
    started = now()
    status("RUNNING", board_date=target_date, message="Buscando agenda, odds e previsões de futebol")

    api_key = os.getenv("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        status(
            "WAITING_FOR_API_KEY",
            board_date=target_date,
            message="API_FOOTBALL_KEY ainda não está configurada nos Secrets do GitHub Actions",
        )
        return 0

    try:
        client = ApiFootballClient(api_key)
        fixtures = client.fixtures_by_date(target_date)
        candidates = eligible_fixtures(fixtures, max_candidates=max_candidates)
        analyses: list[dict[str, Any]] = []

        for fixture_row in candidates:
            fixture_id = int((fixture_row.get("fixture") or {}).get("id"))
            try:
                prediction = client.prediction_for_fixture(fixture_id)
                odds = client.odds_for_fixture(fixture_id)
                analyses.append(analyze_fixture(fixture_row, prediction, odds))
            except ApiFootballError as exc:
                fixture = fixture_row.get("fixture") or {}
                teams = fixture_row.get("teams") or {}
                analyses.append(
                    {
                        "fixture_id": fixture.get("id"),
                        "kickoff_iso": fixture.get("date"),
                        "league": (fixture_row.get("league") or {}).get("name") or "",
                        "country": (fixture_row.get("league") or {}).get("country") or "",
                        "home_team": (teams.get("home") or {}).get("name") or "Mandante",
                        "away_team": (teams.get("away") or {}).get("name") or "Visitante",
                        "decision": "REJECTED",
                        "status": "REJECTED",
                        "score": 0,
                        "reasons": [str(exc)],
                    }
                )

        approved, rejected = rank_analyses(analyses, top_limit=TOP_LIMIT)
        with_odds = sum(1 for row in analyses if row.get("odd"))
        deep = sum(1 for row in analyses if row.get("probability") is not None and row.get("odd"))
        history = historical_summary()
        finished = now()

        payload = {
            "sport": "football",
            "model_version": "football-selective-v1.0",
            "data_mode": "API_FOOTBALL",
            "data_sources": ["API-Football fixtures", "API-Football predictions", "API-Football pre-match odds"],
            "operational_date": started.date().isoformat(),
            "board_date": target_date,
            "board_mode": "D+1",
            "board_status": "READY" if analyses else "NO_FIXTURES",
            "last_run_at": finished.isoformat(),
            "fixtures_found": len(fixtures),
            "fixtures_analyzed": len(analyses),
            "matches_with_odds": with_odds,
            "deep_analyzed_matches": deep,
            "approved": approved,
            "rejected": rejected,
            "all_matches": analyses,
            "top_limit": TOP_LIMIT,
            "history_summary": history,
            "api_requests": client.request_count,
            "criteria": {
                "market": "Vencedor da partida (1X2)",
                "odd_range": "1.50-2.00",
                "min_probability": 0.58,
                "min_edge": 0.03,
                "min_score": 70,
            },
        }
        dump(DASHBOARD / "data.json", payload)
        dump(HISTORY / f"{target_date}.json", payload)
        status(
            "SUCCESS",
            board_date=target_date,
            board_status=payload["board_status"],
            fixtures_found=len(fixtures),
            fixtures_analyzed=len(analyses),
            approved=len(approved),
            api_requests=client.request_count,
            message="Análise de futebol concluída",
        )
        return 0
    except ApiFootballError as exc:
        status("FAILED", board_date=target_date, message=str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        status("FAILED", board_date=target_date, message=f"Unexpected error: {exc}")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="InvestBet football D+1 analyzer")
    parser.add_argument("--date", help="Board date YYYY-MM-DD. Defaults to tomorrow in America/Sao_Paulo")
    parser.add_argument("--max-candidates", type=int, default=int(os.getenv("FOOTBALL_MAX_CANDIDATES", "18")))
    args = parser.parse_args()
    target = args.date or (now().date() + timedelta(days=1)).isoformat()
    return run(target, max_candidates=max(1, min(args.max_candidates, 30)))


if __name__ == "__main__":
    raise SystemExit(main())
