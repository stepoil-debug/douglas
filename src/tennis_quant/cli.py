from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from tennis_quant.config import ROOT, load_model_config
from tennis_quant.history import record_analysis_history
from tennis_quant.learning import aggregate_knowledge, record_learning_board
from tennis_quant.pipeline import analyze_day
from tennis_quant.providers.public_tennis import PublicTennisProvider
from tennis_quant.results import aggregate_metrics, reconcile_recent
from tennis_quant.sequence import freeze_sequence
from tennis_quant.storage import write_json

TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _today_brazil() -> str:
    return datetime.now(TIMEZONE).date().isoformat()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _diagnostics(payload: dict, cfg: dict, provider: PublicTennisProvider) -> None:
    payload["data_sources"] = [
        f"Live: {provider.live_source}",
        "Histórico: Sackmann-format ATP (espelho público + fallback original)",
    ]
    rejected = payload.get("rejected", []) or []
    counts: Counter[str] = Counter()
    for row in rejected:
        counts.update(row.get("reject_reasons", []) or [])
    payload["rejection_summary"] = dict(counts.most_common())

    s = cfg["selection"]
    near: list[dict] = []
    for row in rejected:
        odd = (row.get("selected_market") or {}).get("best_odd")
        if odd is None or not (s["min_odd"] <= float(odd) <= s["max_odd"]):
            continue
        reasons = list(row.get("reject_reasons", []) or [])
        near.append({
            "selected_player": row.get("selected_player"),
            "opponent": row.get("opponent"),
            "match": row.get("match"),
            "selected_market": row.get("selected_market"),
            "odd": odd,
            "signals": row.get("signals") or {},
            "final_probability": row.get("final_probability"),
            "confidence": row.get("confidence"),
            "edge_pp": row.get("edge_pp"),
            "data_quality": row.get("data_quality"),
            "disagreement_pp": row.get("disagreement_pp"),
            "reject_reasons": reasons,
            "failed_gates": len(reasons),
        })
    near.sort(key=lambda x: (
        x["failed_gates"],
        -(float(x.get("confidence") or 0)),
        -(float(x.get("final_probability") or 0)),
    ))
    payload["near_misses"] = near[:10]


def _waiting_or_stale_board(
    board_path: Path,
    operational_day: date,
    board_date: date,
    cfg: dict,
    provider: PublicTennisProvider,
    error: Exception,
    reconciliation: dict,
    metrics: dict,
    knowledge: dict,
) -> dict:
    previous = _read_json(board_path) if board_path.exists() else {}
    has_good_previous = bool(
        previous
        and previous.get("board_date") == board_date.isoformat()
        and int(previous.get("fixtures_analyzed") or 0) > 0
        and previous.get("board_status") != "WAITING_FOR_D1_SCHEDULE"
    )
    if has_good_previous:
        payload = previous
        payload["board_status"] = "STALE_LAST_GOOD_BOARD"
        payload["refresh_status"] = "DEGRADED"
    else:
        payload = {
            "date": board_date.isoformat(),
            "operational_date": operational_day.isoformat(),
            "board_date": board_date.isoformat(),
            "board_mode": "D+1",
            "board_status": "WAITING_FOR_D1_SCHEDULE",
            "refresh_status": "WAITING",
            "model_version": cfg["model_version"],
            "data_mode": "NO_API",
            "fixtures_analyzed": 0,
            "prematch_atp_singles": 0,
            "matches_with_odds": 0,
            "deep_analyzed_matches": 0,
            "approved": [],
            "shadow": [],
            "rejected": [],
            "near_misses": [],
            "unresolved_players": [],
            "history_summary": {},
            "learning_summary": {"matches": 0, "status": "WAITING_FOR_D1_SCHEDULE"},
        }
    payload["operational_date"] = operational_day.isoformat()
    payload["board_date"] = board_date.isoformat()
    payload["board_mode"] = "D+1"
    payload["last_refresh_attempt_at"] = datetime.now(TIMEZONE).isoformat()
    payload["refresh_error"] = str(error)[-500:]
    payload["result_reconciliation"] = reconciliation
    payload["metrics"] = metrics
    payload["knowledge"] = knowledge
    payload["source_requests"] = provider.source_requests
    payload["last_run_at"] = datetime.now(TIMEZONE).isoformat()
    if not payload.get("data_sources"):
        payload["data_sources"] = [
            "Live D+1: aguardando publicação da agenda pública",
            "Histórico: Sackmann-format ATP",
        ]
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Tennis Quant Engine - D+1 no sports API")
    parser.add_argument("--date", default=_today_brazil(), help="Operational day in America/Sao_Paulo")
    parser.add_argument("--h2h-budget", type=int, default=int(os.getenv("H2H_BUDGET", "40")))
    parser.add_argument("--results-days", type=int, default=3)
    args = parser.parse_args()

    operational_day = date.fromisoformat(args.date)
    board_date = operational_day + timedelta(days=1)
    cfg = load_model_config()
    provider = PublicTennisProvider(ROOT)
    board_path = ROOT / "data" / "boards" / f"{board_date.isoformat()}.json"

    # Freeze the already-published six-game list before any new market refresh can
    # change the ranking. If the list for this board date was already created, this
    # call is a no-op and the selections remain immutable.
    published_board = _read_json(ROOT / "dashboard" / "data.json")
    if str(published_board.get("board_date") or "") == board_date.isoformat():
        freeze_sequence(ROOT, published_board)

    # Lane 1: current/past dates are result-only. Their pre-match thesis is never
    # recomputed after the day rolls over.
    try:
        resolved = reconcile_recent(provider, ROOT, operational_day, args.results_days)
    except Exception as exc:
        resolved = []
        reconciliation = {"status": "DEGRADED", "error": str(exc)[:300]}
    else:
        reconciliation = {"status": "OK", "resolved": len(resolved)}

    # Result learning is independent from tomorrow's source availability.
    knowledge = aggregate_knowledge(ROOT)
    metrics = aggregate_metrics(ROOT)

    # Lane 2: repeatedly refresh every available ATP Singles match for tomorrow.
    # A D+1 schedule not published yet is a normal waiting state, not a system
    # failure. This keeps today's result/learning lane alive and preserves the last
    # valid future board rather than replacing it with zeros.
    try:
        payload = analyze_day(provider, board_date, cfg, ROOT, args.h2h_budget)
        fixtures = provider.fixtures(board_date)
        odds_by_match = provider.odds(board_date)
        all_candidates = (
            (payload.get("approved", []) or [])
            + (payload.get("shadow", []) or [])
            + (payload.get("rejected", []) or [])
        )
        ledger = record_analysis_history(
            ROOT,
            board_date.isoformat(),
            fixtures,
            odds_by_match,
            all_candidates,
            cfg["model_version"],
            provider.live_source,
        )
        learning = record_learning_board(
            ROOT,
            board_date.isoformat(),
            all_candidates,
            cfg["model_version"],
            provider.live_source,
        )
        sequence = freeze_sequence(ROOT, payload)
        payload["board_status"] = "PROVISIONAL_UNTIL_DAY_ROLLOVER"
        payload["refresh_status"] = "SUCCESS"
        payload["history_summary"] = ledger.get("summary", {})
        payload["learning_summary"] = {
            "matches": len(learning.get("matches", [])),
            "status": learning.get("status"),
        }
        payload["sequence_summary"] = {
            "status": sequence.get("status"),
            "games": len(sequence.get("games", []) or []),
            "created_at": sequence.get("created_at"),
        }
        payload["result_reconciliation"] = reconciliation
        payload["metrics"] = metrics
        payload["knowledge"] = knowledge
        payload["last_run_at"] = datetime.now(TIMEZONE).isoformat()
        payload["source_requests"] = provider.source_requests
        payload["refresh_error"] = None
        payload["operational_date"] = operational_day.isoformat()
        payload["board_date"] = board_date.isoformat()
        payload["board_mode"] = "D+1"
        _diagnostics(payload, cfg, provider)
    except Exception as exc:
        payload = _waiting_or_stale_board(
            board_path,
            operational_day,
            board_date,
            cfg,
            provider,
            exc,
            reconciliation,
            metrics,
            knowledge,
        )

    write_json(board_path, payload)
    write_json(ROOT / "dashboard" / "data.json", payload)

    print(json.dumps({
        "operational_date": operational_day.isoformat(),
        "board_date": board_date.isoformat(),
        "board_status": payload.get("board_status"),
        "refresh_status": payload.get("refresh_status"),
        "model_version": payload.get("model_version"),
        "fixtures_tomorrow": payload.get("fixtures_analyzed", 0),
        "matches_with_odds": payload.get("matches_with_odds", 0),
        "deep_analyzed_matches": payload.get("deep_analyzed_matches", 0),
        "approved": len(payload.get("approved", []) or []),
        "shadow": len(payload.get("shadow", []) or []),
        "near_misses": len(payload.get("near_misses", []) or []),
        "sequence": payload.get("sequence_summary"),
        "learning_matches": (payload.get("learning_summary") or {}).get("matches", 0),
        "knowledge_resolved": (knowledge.get("overall") or {}).get("n", 0),
        "results_reconciled": len(resolved),
        "source_requests": provider.source_requests,
        "refresh_error": payload.get("refresh_error"),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
