from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def load_model_config(path: str | None = None) -> dict[str, Any]:
    config_path = Path(path or os.getenv("MODEL_CONFIG", ROOT / "config" / "model.json"))
    with config_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default
