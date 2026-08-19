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
from .multi_market import build_multi_market_legs, family_counts
from .ticket_builder import TARGET_TICKETS, build_legs, build_tickets, rank_fixture_candidates, summarize_match

TZ = ZoneInfo("America/Sao_Paulo")
ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"
HISTORY = ROOT / "data" / "football" / "history"


def now() -> datetime:
    return datetime.now(TZ)


def dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
            row = load(path)
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


def _merge_legs(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, str, str], dict[str, Any]] = {}
    for group in groups:
        for leg in group:
            key = (
                leg.get("fixture_id"),
                str(leg.get("market") or "").strip().casefold(),
                str(leg.get("selection") or "").strip().casefold(),
            )
            current = unique.get(key)
            if current is None or float(leg.get("score") or 0) > float(current.get("score") or 0):
                unique[key] = leg
    return sorted(
        unique.values(),
        key=lambda row: (-float(row.get("score") or 0), -float(row.get("model_probability") or 0)),
    )


def _restore_locked_board(target_date: str) -> bool:
    path = HISTORY / f"{target_date}.json"
    if not path.exists():
        return False
    try:
        payload = load(path)
    except Exception:
        return False
    lock = payload.get("ticket_lock") or {}
    tickets = payload.get("tickets") or []
    if not lock.get("locked") or len(tickets) < TARGET_TICKETS:
        return False
    payload["history_summary"] = historical_summary()
    dump(DASHBOARD / "data.json", payload)
    status(
        "SUCCESS",
        board_date=target_date,
        board_mode="TODAY",
        board_status=payload.get("board_status") or "READY",
        fixtures_found=payload.get("fixtures_found") or 0,
        fixtures_analyzed=payload.get("fixtures_analyzed") or 0,
        tickets_ready=len(tickets),
        target_tickets=TARGET_TICKETS,
        execution_bookmaker=payload.get("execution_bookmaker") or "Betano",
        execution_ready=bool(payload.get("execution_ready")),
        ticket_lock=True,
        message="Os 3 bilhetes oficiais do dia já foram publicados e estão travados para preservar GREEN/RED e a simulação de banca.",
    )
    print(f"Locked board restored for {target_date}; analysis skipped.")
    return True


def run(target_date: str, max_candidates: int, max_odds_pages: int) -> int:
    if _restore_locked_board(target_date):
        return 0

    started = now()
    status(
        "RUNNING",
        board_date=target_date,
        board_mode="TODAY",
        message="Analisando gols, escanteios, cartões, chutes e mercados de resultado para montar 3 bilhetes entre odd 1.50 e 2.00",
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

            base_legs = build_legs(fixture, prediction, odds_by_fixture.get(fixture_id))
            multi_legs = build_multi_market_legs(fixture, odds_by_fixture.get(fixture_id))
            legs = _merge_legs(base_legs, multi_legs)
            all_legs.extend(legs)
            match_summary = summarize_match(fixture, prediction, legs)
            match_summary["market_family_counts"] = family_counts(legs)
            matches.append(match_summary)
            tickets = build_tickets(all_legs, target=TARGET_TICKETS)

            # Analyze a meaningful sample even when three combinations already exist.
            if len(tickets) >= TARGET_TICKETS and index >= 9:
                break

        history = historical_summary()
        finished = now()
        matches_with_markets = len(odds_by_fixture)
        usable_matches = sum(1 for row in matches if row.get("decision") == "USABLE")
        strict_tickets = sum(1 for row in tickets if row.get("quality_tier") == "STRICT")
        consensus_tickets = sum(1 for row in tickets if row.get("quality_tier") == "CONSENSUS")
        bookmakers_used = sorted({str(row.get("bookmaker") or "") for row in tickets if row.get("bookmaker")})
        family_totals = family_counts(all_legs)
        ticket_family_totals = family_counts([leg for ticket in tickets for leg in (ticket.get("legs") or [])])

        board_status = "READY" if len(tickets) >= TARGET_TICKETS else ("PARTIAL" if tickets else "NO_TICKETS")
        payload = {
            "sport": "football",
            "model_version": "football-multimarket-v4",
            "data_mode": "API_FOOTBALL",
            "data_sources": [
                "API-Football fixtures",
                "API-Football predictions/comparison/H2H",
                "API-Football pre-match odds",
                "bookmaker consensus + common-bookmaker pricing",
                "multi-market totals: goals, corners, yellow cards, shots and shots on target",
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
            "market_analysis": {
                "enabled": True,
                "families": ["GOALS", "CORNERS", "CARDS", "SHOTS", "RESULT"],
                "eligible_by_family": family_totals,
                "selected_by_family": ticket_family_totals,
                "settlement": "automatic for supported full-time totals",
                "correlation_guard": "same fixture cannot be repeated across tickets",
            },
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
                    "Total de gols",
                    "Ambas marcam",
                    "Gols da equipe",
                    "Total de escanteios",
                    "Escanteios da equipe",
                    "Total de cartões amarelos",
                    "Cartões amarelos da equipe",
                    "Total de chutes",
                    "Total de chutes no alvo",
                ],
                "method": "previsão + comparação/H2H + consenso de bookmakers + múltiplos mercados full-time + mesma casa por bilhete + diversificação",
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
            f"3 bilhetes multimercado prontos para hoje; famílias analisadas: gols, escanteios, cartões, chutes e resultado."
            if len(tickets) >= TARGET_TICKETS
            else f"Somente {len(tickets)} bilhete(s) atingiram os filtros multimercado e a faixa 1.50-2.00; nenhum mercado foi fabricado."
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
            market_analysis=True,
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
    parser = argparse.ArgumentParser(description="InvestBet same-day multi-market football analyzer")
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
