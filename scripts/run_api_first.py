from __future__ import annotations

import json
import os
from pathlib import Path

import tennis_quant.cli as cli
from tennis_quant.config import ROOT
from tennis_quant.providers.api_first import ApiFirstTennisProvider


def main() -> None:
    api_key = os.getenv("API_TENNIS_KEY", "").strip()
    if not api_key:
        raise SystemExit(78)

    # Keep the mature D+1 orchestration intact and only swap its provider.
    cli.PublicTennisProvider = lambda root: ApiFirstTennisProvider(root, api_key)  # type: ignore[assignment]
    cli.main()

    payload_path = Path(ROOT) / "dashboard" / "data.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["data_mode"] = "API_FIRST"
    payload["api_live_source"] = "API-Tennis"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    board_date = str(payload.get("board_date") or payload.get("date") or "")
    board_path = Path(ROOT) / "data" / "boards" / f"{board_date}.json"
    if board_date and board_path.exists():
        board = json.loads(board_path.read_text(encoding="utf-8"))
        board["data_mode"] = "API_FIRST"
        board["api_live_source"] = "API-Tennis"
        board_path.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")

    # The current CLI treats a missing future board as a normal waiting state.
    # For a manual API-first run, signal that condition so the workflow can fall
    # back to the existing public collector instead of publishing a false success.
    if payload.get("refresh_status") != "SUCCESS" or int(payload.get("fixtures_analyzed") or 0) <= 0:
        raise SystemExit(42)


if __name__ == "__main__":
    main()
