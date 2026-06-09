from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import runs_dir


def new_run_id() -> str:
    return "run_" + str(int(time.time() * 1000))


def save_run(run_id: str, payload: dict[str, Any]) -> Path:
    root = runs_dir() / run_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "run.json"
    existing = load_run(run_id) if path.exists() else {}
    existing.update(payload)
    existing.setdefault("run_id", run_id)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    return path


def load_run(run_id: str) -> dict[str, Any]:
    path = runs_dir() / run_id / "run.json"
    if not path.exists():
        raise FileNotFoundError(f"run not found: {run_id}")
    return json.loads(path.read_text())


def list_runs() -> list[dict[str, Any]]:
    root = runs_dir()
    if not root.exists():
        return []
    result = []
    for path in sorted(root.glob("*/run.json"), reverse=True):
        try:
            result.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return result
