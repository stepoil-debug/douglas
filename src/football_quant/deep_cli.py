from __future__ import annotations

import argparse
import os

from .cli import now, run


def main() -> int:
    parser = argparse.ArgumentParser(description="InvestBet deep same-day football analyzer")
    parser.add_argument("--date", help="Data YYYY-MM-DD. Padrão: hoje em America/Sao_Paulo")
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=int(os.getenv("FOOTBALL_MAX_CANDIDATES", "60")),
    )
    parser.add_argument(
        "--max-odds-pages",
        type=int,
        default=int(os.getenv("FOOTBALL_MAX_ODDS_PAGES", "15")),
    )
    args = parser.parse_args()
    target = args.date or now().date().isoformat()
    return run(
        target,
        max_candidates=max(10, min(args.max_candidates, 80)),
        max_odds_pages=max(1, min(args.max_odds_pages, 20)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
