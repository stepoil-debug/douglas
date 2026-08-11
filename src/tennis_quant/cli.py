from __future__ import annotations

import argparse
import json
import os
from datetime import date

from tennis_quant.config import ROOT, load_model_config
from tennis_quant.pipeline import analyze_day
from tennis_quant.providers.api_tennis import ApiTennisProvider


def main() -> None:
    parser = argparse.ArgumentParser(description="Tennis Quant Engine")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--h2h-budget", type=int, default=int(os.getenv("H2H_BUDGET", "40")))
    args = parser.parse_args()

    api_key = os.getenv("API_TENNIS_KEY")
    if not api_key:
        raise SystemExit("Missing API_TENNIS_KEY. Add it as a GitHub Actions secret.")
    cfg = load_model_config()
    provider = ApiTennisProvider(api_key)
    payload = analyze_day(provider, date.fromisoformat(args.date), cfg, ROOT, args.h2h_budget)
    print(json.dumps({
        "date": payload["date"],
        "fixtures_analyzed": payload["fixtures_analyzed"],
        "approved": len(payload["approved"]),
        "shadow": len(payload["shadow"]),
    }, indent=2))


if __name__ == "__main__":
    main()
