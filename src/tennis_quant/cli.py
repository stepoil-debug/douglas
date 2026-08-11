from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from tennis_quant.config import ROOT, load_model_config
from tennis_quant.history import record_analysis_history
from tennis_quant.pipeline import analyze_day
from tennis_quant.providers.public_tennis import PublicTennisProvider
from tennis_quant.results import aggregate_metrics, reconcile_recent
from tennis_quant.storage import write_json

TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _today_brazil() -> str:
    return datetime.now(TIMEZONE).date().isoformat()


def _diagnostics(payload: dict, cfg: dict, provider: PublicTennisProvider) -> None:
    """Add observability only. This never changes approval/rejection decisions."""
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
            "odd": odd,
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
    parser = argparse.ArgumentParser(description="Tennis Quant Engine - no sports API")
    parser.add_argument("--date", default=_today_brazil())
    parser.add_argument("--h2h-budget", type=int, default=int(os.getenv("H2H_BUDGET", "40")))
    parser.add_argument("--results-days", type=int, default=1)
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    cfg = load_model_config()
    provider = PublicTennisProvider(ROOT)
    payload = analyze_day(provider, target_date, cfg, ROOT, args.h2h_budget)

    # The provider caches the day, so these calls do not scrape the source again.
    fixtures = provider.fixtures(target_date)
    odds_by_match = provider.odds(target_date)
    all_candidates = (payload.get("approved", []) or []) + (payload.get("shadow", []) or []) + (payload.get("rejected", []) or [])
    ledger = record_analysis_history(
        ROOT,
        target_date.isoformat(),
        fixtures,
        odds_by_match,
        all_candidates,
        cfg["model_version"],
        provider.live_source,
    )
    payload["history_summary"] = ledger.get("summary", {})

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
    _diagnostics(payload, cfg, provider)

    write_json(ROOT / "data" / "daily" / f"{target_date.isoformat()}.json", payload)
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
        "near_misses": len(payload.get("near_misses", [])),
        "rejection_summary": payload.get("rejection_summary"),
        "source_requests": provider.source_requests,
        "unresolved_players": payload.get("unresolved_players"),
        "bootstrap": payload.get("bootstrap"),
        "history": payload.get("history_summary"),
        "results_reconciled": len(resolved),
        "resolved_approved_total": metrics["total_approved_resolved"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
