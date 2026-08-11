from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tennis_quant.config import ROOT, load_model_config
from tennis_quant.history import record_analysis_history
from tennis_quant.learning import aggregate_knowledge, record_learning_board
from tennis_quant.pipeline import analyze_day
from tennis_quant.providers.public_tennis import PublicTennisProvider
from tennis_quant.results import aggregate_metrics, reconcile_recent
from tennis_quant.storage import write_json

TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _today_brazil() -> str:
    return datetime.now(TIMEZONE).date().isoformat()


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

    # Lane 1: today/past are result-only. Never recompute their pre-match thesis.
    try:
        resolved = reconcile_recent(provider, ROOT, operational_day, args.results_days)
    except Exception as exc:
        resolved = []
        reconciliation = {"status": "DEGRADED", "error": str(exc)[:300]}
    else:
        reconciliation = {"status": "OK", "resolved": len(resolved)}

    knowledge = aggregate_knowledge(ROOT)
    metrics = aggregate_metrics(ROOT)

    # Lane 2: all available ATP Singles for tomorrow are analyzed repeatedly during
    # the current day. The last D-1 run naturally becomes the final board; on match
    # day this date is no longer analyzed, only reconciled above.
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

    payload["operational_date"] = operational_day.isoformat()
    payload["board_date"] = board_date.isoformat()
    payload["board_mode"] = "D+1"
    payload["board_status"] = "PROVISIONAL_UNTIL_DAY_ROLLOVER"
    payload["history_summary"] = ledger.get("summary", {})
    payload["learning_summary"] = {
        "matches": len(learning.get("matches", [])),
        "status": learning.get("status"),
    }
    payload["result_reconciliation"] = reconciliation
    payload["metrics"] = metrics
    payload["knowledge"] = knowledge
    payload["last_run_at"] = datetime.now(TIMEZONE).isoformat()
    payload["source_requests"] = provider.source_requests
    _diagnostics(payload, cfg, provider)

    write_json(ROOT / "data" / "boards" / f"{board_date.isoformat()}.json", payload)
    write_json(ROOT / "dashboard" / "data.json", payload)

    print(json.dumps({
        "operational_date": operational_day.isoformat(),
        "board_date": board_date.isoformat(),
        "model_version": payload["model_version"],
        "data_mode": payload.get("data_mode"),
        "fixtures_tomorrow": payload["fixtures_analyzed"],
        "prematch_atp_singles": payload.get("prematch_atp_singles"),
        "matches_with_odds": payload.get("matches_with_odds"),
        "deep_analyzed_matches": payload.get("deep_analyzed_matches"),
        "approved": len(payload["approved"]),
        "shadow": len(payload["shadow"]),
        "near_misses": len(payload.get("near_misses", [])),
        "learning_matches": len(learning.get("matches", [])),
        "knowledge_resolved": (knowledge.get("overall") or {}).get("n", 0),
        "results_reconciled": len(resolved),
        "rejection_summary": payload.get("rejection_summary"),
        "source_requests": provider.source_requests,
        "unresolved_players": payload.get("unresolved_players"),
        "bootstrap": payload.get("bootstrap"),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
