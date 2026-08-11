from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from tennis_quant.config import ROOT, load_model_config
from tennis_quant.pipeline import analyze_day
from tennis_quant.providers.public_tennis import PublicTennisProvider
from tennis_quant.results import aggregate_metrics, reconcile_recent
from tennis_quant.storage import write_json

TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _today_brazil() -> str:
    return datetime.now(TIMEZONE).date().isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Tennis Quant Engine - no sports API")
    parser.add_argument("--date", default=_today_brazil())
    parser.add_argument("--h2h-budget", type=int, default=int(os.getenv("H2H_BUDGET", "40")))
    parser.add_argument("--results-days", type=int, default=1)
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    cfg = load_model_config()
    provider = PublicTennisProvider(ROOT)
    payload = analyze_day(provider, target_date, cfg, ROOT, args.h2h_budget)

    # Result reconciliation is best-effort because public result sources can lag. It never blocks
    # today's pre-match analysis if yesterday's page is unavailable.
    try:
        resolved = reconcile_recent(provider, ROOT, target_date, args.results_days)
    except Exception as exc:
        resolved = []
        payload["result_reconciliation"] = {"status": "DEGRADED", "error": str(exc)[:300]}

    metrics = aggregate_metrics(ROOT)
    payload["metrics"] = metrics
    payload["last_run_at"] = datetime.now(TIMEZONE).isoformat()
    payload["source_requests"] = provider.source_requests
    write_json(ROOT / "dashboard" / "data.json", payload)

    print(json.dumps({
        "date": payload["date"],
        "model_version": payload["model_version"],
        "data_mode": payload.get("data_mode"),
        "data_sources": payload.get("data_sources"),
        "fixtures_analyzed": payload["fixtures_analyzed"],
        "prematch_atp_singles": payload.get("prematch_atp_singles"),
        "matches_with_odds": payload.get("matches_with_odds"),
        "deep_analyzed_matches": payload.get("deep_analyzed_matches"),
        "approved": len(payload["approved"]),
        "shadow": len(payload["shadow"]),
        "source_requests": provider.source_requests,
        "unresolved_players": payload.get("unresolved_players"),
        "bootstrap": payload.get("bootstrap"),
        "results_reconciled": len(resolved),
        "resolved_approved_total": metrics["total_approved_resolved"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
