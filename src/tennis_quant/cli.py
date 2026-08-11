from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from tennis_quant.config import ROOT, load_model_config
from tennis_quant.pipeline import analyze_day
from tennis_quant.providers.api_tennis import ApiTennisProvider
from tennis_quant.results import aggregate_metrics, reconcile_recent
from tennis_quant.storage import write_json

TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _today_brazil() -> str:
    return datetime.now(TIMEZONE).date().isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Tennis Quant Engine")
    parser.add_argument("--date", default=_today_brazil())
    parser.add_argument("--h2h-budget", type=int, default=int(os.getenv("H2H_BUDGET", "40")))
    parser.add_argument("--results-days", type=int, default=3)
    args = parser.parse_args()

    api_key = os.getenv("API_TENNIS_KEY")
    if not api_key:
        raise SystemExit("Missing API_TENNIS_KEY. Add it as a GitHub Actions secret.")
    target_date = date.fromisoformat(args.date)
    cfg = load_model_config()
    provider = ApiTennisProvider(api_key)
    payload = analyze_day(provider, target_date, cfg, ROOT, args.h2h_budget)
    resolved = reconcile_recent(provider, ROOT, target_date, args.results_days)
    metrics = aggregate_metrics(ROOT)
    payload["metrics"] = metrics
    payload["last_run_at"] = datetime.now(TIMEZONE).isoformat()
    payload["api_requests"] = provider.request_count
    write_json(ROOT / "dashboard" / "data.json", payload)

    print(json.dumps({
        "date": payload["date"],
        "model_version": payload["model_version"],
        "fixtures_analyzed": payload["fixtures_analyzed"],
        "prematch_atp_singles": payload.get("prematch_atp_singles"),
        "matches_with_odds": payload.get("matches_with_odds"),
        "deep_analyzed_matches": payload.get("deep_analyzed_matches"),
        "approved": len(payload["approved"]),
        "shadow": len(payload["shadow"]),
        "api_requests": provider.request_count,
        "bootstrap": payload.get("bootstrap"),
        "results_reconciled": len(resolved),
        "resolved_approved_total": metrics["total_approved_resolved"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
