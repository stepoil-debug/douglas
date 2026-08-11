from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_snapshot(base: Path, target_date: str, payload: dict[str, Any]) -> Path:
    path = base / "predictions" / target_date / f"{payload['match']['match_id']}.json"
    if path.exists():
        # Frozen prediction: never overwrite the first pre-match snapshot.
        return path
    payload = {**payload, "frozen_at": datetime.now(timezone.utc).isoformat()}
    write_json(path, payload)
    return path
