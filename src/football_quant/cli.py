from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .api_football import ApiFootballClient, ApiFootballError, fixture_id_from_odds
from .ticket_builder import TARGET_TICKETS, build_legs, build_tickets, rank_fixture_candidates, summarize_match

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"
HISTORY = ROOT / "data" / "football" / "history"
# Any change in this module triggers the GitHub-only analysis workflow.


def now() -> datetime:
    return datetime.now(TZ)


def dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def status(state: str, **extra: Any) -> None:
    dump(
        DASHBOARD / "run_status.json",
        {"sport": "football", "status": state, "updated_at": now().isoformat(), **extra},
    )


def historical_summary() -> dict[str, Any]:
    resolved = hits = misses = tickets_resolved = tickets_hit = tickets_miss = 0
    if not HISTORY.exists():
        return {
            "resolved": 0, "hits": 0, "misses": 0, "accuracy": None,
            "tickets_resolved": 0, "tickets_hit": 0, "tickets_miss": 0, "ticket_accuracy": None,
        }
    for path in HISTORY.glob("*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for ticket in row.get("tickets") or []:
            ticket_status = str(ticket.get("status") or "").upper()
            if ticket_status in {"HIT", "GREEN"}:
                tickets_resolved += 1
                tickets_hit += 1
            elif ticket_status in {"MISS", "RED"}:
                tickets_resolved += 1
                tickets_miss += 1
            for leg in ticket.get("legs") or []:
                leg_status = str(leg.get("status") or "").upper()
                if leg_status in {"HIT", "GREEN"}:
                    resolved += 1
                    hits += 1
                elif leg_status in {"MISS", "RED"}:
                    resolved += 1
                    misses += 1
    return {
        "resolved": resolved,
        "hits": hits,
        "misses": misses,
        "accuracy": (hits / resolved) if resolved else None,
        "tickets_resolved": tickets_resolved,
        "tickets_hit": tickets_hit,
        "tickets_miss": tickets_miss,
        "ticket_accuracy": (tickets_hit / tickets_resolved) if tickets_resolved else None,
    }


def _resolve_api_key() -> str:
    for name in ("API_FOOTBALL_KEY", "API_SPORTS_KEY", "FOOTBALL_API_KEY", "APISPORTS_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def run(target_date: str, max_candidates: int, max_odds_pages: int) -> int:
    started = now()
    status(
        "RUNNING",
        board_date=target_date,
        board_mode="TODAY",
        message="Analisando jogos de hoje e montando 3 bilhetes entre odd 1.50 e 2.00",
    )

    api_key = _resolve_api_key()
    if not api_key:
        status(
            "WAITING_FOR_API_KEY",
            board_date=target_date,
            board_mode="TODAY",
            tickets_ready=0,
            target_tickets=TARGET_TICKETS,
            message="Motor GitHub pronto; configure API_FOOTBALL_KEY (ou alias aceito) nos Secrets do repositório para ativar dados reais.",
        )
        return 0

    try:
        client = ApiFootballClient(api_key)
        fixtures = client.fixtures_by_date(target_date)
        odds_rows = client.odds_by_date(target_date, max_pages=max_odds_pages)
        odds_by_fixture: dict[int, dict[str, Any]] = {}
        for row in odds_rows:
            fixture_id = fixture_id_from_odds(row)
            if fixture_id:
                odds_by_fixture[fixture_id] = row

        ranked = rank_fixture_candidates(fixtures, odds_by_fixture, max_candidates=max_candidates)
        matches: list[dict[str, Any]] = []
        all_legs: list[dict[str, Any]] = []
        tickets: list[dict[str, Any]] = []
        prediction_available = 0

        for index, fixture in enumerate(ranked):
            info = fixture.get("fixture") or {}
            fixture_id = int(info.get("id"))
            prediction = None
            try:
                prediction = client.prediction_for_fixture(fixture_id)
            except ApiFootballError:
                prediction = None
            if prediction:
                prediction_available += 1
            legs = build_legs(fixture, prediction, odds_by_fixture.get(fixture_id))
            all_legs.extend(legs)
            matches.append(summarize_match(fixture, prediction, legs))
            tickets = build_tickets(all_legs, target=TARGET_TICKETS)

            if len(tickets) >= TARGET_TICKETS and index >= 9:
                break

        history = historical_summary()
        finished = now()
        matches_with_markets = len(odds_by_fixture)
        usable_matches = sum(1 for row in matches if row.get("decision") == "USABLE")
        strict_tickets = sum(1 for row in tickets if row.get("quality_tier") == "STRICT")
        consensus_tickets = sum(1 for row in tickets if row.get("quality_tier") == "CONSENSUS")
        bookmakers_used = sorted({str(row.get("bookmaker") or "") for row in tickets if row.get("bookmaker")})

        board_status = "READY" if len(tickets) >= TARGET_TICKETS else ("PARTIAL" if tickets else "NO_TICKETS")
        payload = {
            "sport": "football",
            "model_version": "football-3tickets-v2.2",
            "data_mode": "API_FOOTBALL",
            "data_sources": [
                "API-Football fixtures",
                "API-Football predictions/comparison/H2H",
                "API-Football pre-match odds",
                "bookmaker consensus + common-bookmaker pricing",
            ],
            "operational_date": started.date().isoformat(),
            "board_date": target_date,
            "board_mode": "TODAY",
            "board_status": board_status,
            "last_run_at": finished.isoformat(),
            "fixtures_found": len(fixtures),
            "fixtures_with_markets": matches_with_markets,
            "fixtures_ranked": len(ranked),
            "fixtures_analyzed": len(matches),
            "predictions_available": prediction_available,
            "usable_matches": usable_matches,
            "eligible_legs": len(all_legs),
            "tickets": tickets,
            "tickets_ready": len(tickets),
            "ticket_target": TARGET_TICKETS,
            "strict_tickets": strict_tickets,
            "consensus_tickets": consensus_tickets,
            "bookmakers_used": bookmakers_used,
            "all_matches": matches,
            "history_summary": history,
            "api_requests": client.request_count,
            "api_requests_remaining": client.remaining_requests,
            "api_minute_limit": client.minute_limit,
            "api_minute_remaining": client.minute_remaining,
            "criteria": {
                "ticket_odd_range": "1.50-2.00",
                "ticket_target": TARGET_TICKETS,
                "same_day_only": True,
                "max_legs": 2,
                "markets": [
                    "Vencedor da partida",
                    "Dupla chance",
                    "Mais de 1.5 gols",
                    "Menos de 4.5 gols",
                    "Equipe favorita marca 1+ gol",
                ],
                "method": "previsão + comparação/H2H + consenso de bookmakers + fallback conservador + mesma casa por bilhete + diversificação",
            },
            "approved": tickets,
            "rejected": [row for row in matches if row.get("decision") != "USABLE"],
            "matches_with_odds": matches_with_markets,
            "deep_analyzed_matches": prediction_available,
            "top_limit": TARGET_TICKETS,
        }
        dump(DASHBOARD / "data.json", payload)
        dump(HISTORY / f"{target_date}.json", payload)

        message = (
            f"3 bilhetes prontos para hoje; todos precificados em uma única bookmaker por bilhete ({strict_tickets} estritos, {consensus_tickets} consenso)."
            if len(tickets) >= TARGET_TICKETS
            else f"Somente {len(tickets)} bilhete(s) executáveis atingiram odd 1.50-2.00; nenhum mercado ou preço foi fabricado."
        )
        status(
            "SUCCESS",
            board_date=target_date,
            board_mode="TODAY",
            board_status=board_status,
            fixtures_found=len(fixtures),
            fixtures_analyzed=len(matches),
            tickets_ready=len(tickets),
            target_tickets=TARGET_TICKETS,
            api_requests=client.request_count,
            message=message,
        )
        return 0
    except ApiFootballError as exc:
        status("FAILED", board_date=target_date, board_mode="TODAY", message=str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        status("FAILED", board_date=target_date, board_mode="TODAY", message=f"Unexpected error: {exc}")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="InvestBet same-day football ticket analyzer")
    parser.add_argument("--date", help="Data YYYY-MM-DD. Padrão: hoje em America/Sao_Paulo")
    parser.add_argument("--max-candidates", type=int, default=int(os.getenv("FOOTBALL_MAX_CANDIDATES", "14")))
    parser.add_argument("--max-odds-pages", type=int, default=int(os.getenv("FOOTBALL_MAX_ODDS_PAGES", "6")))
    args = parser.parse_args()
    target = args.date or now().date().isoformat()
    return run(
        target,
        max_candidates=max(10, min(args.max_candidates, 30)),
        max_odds_pages=max(1, min(args.max_odds_pages, 20)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
