from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import runs_dir


def new_run_id() -> str:
    return "run_" + str(int(time.time() * 1000))


def _run_path(run_id: str) -> Path:
    return runs_dir() / run_id / "run.json"


def _read_run(run_id: str) -> dict[str, Any]:
    path = _run_path(run_id)
    if not path.exists():
        raise FileNotFoundError(f"run not found: {run_id}")
    return json.loads(path.read_text())


def save_run(run_id: str, payload: dict[str, Any]) -> Path:
    root = runs_dir() / run_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / "run.json"
    existing = _read_run(run_id) if path.exists() else {}
    existing.update(payload)
    existing.setdefault("run_id", run_id)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    return path


def load_run(run_id: str) -> dict[str, Any]:
    return _read_run(resolve_run_id(run_id))


def resolve_run_id(run_id: str) -> str:
    current = run_id
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        try:
            row = _read_run(current)
        except FileNotFoundError:
            return current
        canonical = str(row.get("canonical_run_id") or "").strip()
        if not canonical or canonical == current:
            return current
        current = canonical
    raise ValueError(f"run alias cycle detected: {run_id}")


def promote_run(draft_run_id: str, canonical_run_id: str, payload: dict[str, Any]) -> Path:
    if not canonical_run_id:
        raise ValueError("canonical run id is required")

    try:
        draft = _read_run(draft_run_id)
    except FileNotFoundError:
        draft = {}

    canonical_payload = {
        **draft,
        **payload,
        "run_id": canonical_run_id,
        "canonical_run_id": canonical_run_id,
        "draft_run_id": draft_run_id,
    }
    path = save_run(canonical_run_id, canonical_payload)

    if draft_run_id != canonical_run_id:
        save_run(draft_run_id, {
            "run_id": draft_run_id,
            "canonical_run_id": canonical_run_id,
            "status": "redirected",
            "message_id": canonical_payload.get("message_id") or 0,
            "task_id": canonical_payload.get("task_id") or "",
        })
    return path


def list_runs() -> list[dict[str, Any]]:
    root = runs_dir()
    if not root.exists():
        return []
    result = []
    for path in sorted(root.glob("*/run.json"), reverse=True):
        try:
            row = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        run_id = str(row.get("run_id") or path.parent.name)
        canonical = str(row.get("canonical_run_id") or "").strip()
        if canonical and canonical != run_id:
            continue
        result.append(row)
    return result
