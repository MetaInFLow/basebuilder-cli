from __future__ import annotations

import json
from typing import Any


def ok_envelope(operation: str, data: Any | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": operation,
        "data": data if data is not None else {},
        "meta": meta or {},
    }


def error_envelope(
    operation: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
        "meta": meta or {},
    }


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
