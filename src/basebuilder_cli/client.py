from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


class ApiError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class StreamEvent:
    type: str
    data: dict[str, Any]


class BaseBuilderApiClient:
    def __init__(self, api_base: str, token: str = "", timeout: float = 60.0):
        self.api_base = api_base.rstrip("/")
        self.token = token
        self.timeout = timeout

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/api/cli/capabilities")

    def device_start(
        self,
        device_name: str,
        *,
        intent: str = "login",
        client_kind: str = "human_cli",
        fingerprint_hash: str = "",
        fingerprint_signals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "device_name": device_name,
            "intent": intent,
            "client_kind": client_kind,
        }
        if fingerprint_hash:
            payload["fingerprint_hash"] = fingerprint_hash
        if fingerprint_signals:
            payload["fingerprint_signals"] = fingerprint_signals
        return self._request("POST", "/api/cli/auth/device/start", payload)

    def device_poll(self, device_code: str) -> dict[str, Any]:
        return self._request("POST", "/api/cli/auth/device/poll", {"device_code": device_code})

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/api/cli/me")

    def logout(self) -> dict[str, Any]:
        return self._request("POST", "/api/cli/auth/logout", {})

    def agent_current(self) -> dict[str, Any]:
        return self._request("GET", "/api/cli/agents/current")

    def agent_upsert(
        self,
        *,
        device_name: str,
        fingerprint_hash: str,
        fingerprint_signals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/api/cli/agents/current", {
            "device_name": device_name,
            "fingerprint_hash": fingerprint_hash,
            "fingerprint_signals": fingerprint_signals or {},
        })

    def agent_unregister(self) -> dict[str, Any]:
        return self._request("DELETE", "/api/cli/agents/current")

    def analyze(self, prompt: str) -> dict[str, Any]:
        return self._request("POST", "/api/cli/build/analyze", {"prompt": prompt})

    def optimize(self, elements: Any, instruction: str, message_id: int | None = None, task_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"elements": _as_mapping(elements), "instruction": instruction}
        if message_id:
            payload["message_id"] = int(message_id)
        if task_id:
            payload["task_id"] = str(task_id)
        return self._request(
            "POST",
            "/api/cli/build/optimize",
            payload,
        )

    def start_build(self, elements: Any, message_id: int | None = None, task_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"confirmed_elements": _as_mapping(elements)}
        if message_id:
            payload["message_id"] = int(message_id)
        if task_id:
            payload["task_id"] = str(task_id)
        return self._request("POST", "/api/cli/build/start", payload)

    def run_snapshot(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/cli/runs/{urllib.parse.quote(run_id)}/snapshot")

    def final_artifact(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/cli/runs/{urllib.parse.quote(run_id)}/artifact")

    def attach_progress(
        self,
        run_id: str,
        *,
        poll_interval: float = 5.0,
        max_polls: int | None = None,
    ) -> Iterable[StreamEvent]:
        polls = 0
        while True:
            payload = self.run_snapshot(run_id)
            yield StreamEvent("snapshot", payload)
            polls += 1

            if _is_terminal_snapshot(payload):
                return
            if max_polls is not None and polls >= max_polls:
                return
            time.sleep(max(0.0, float(poll_interval)))

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token

        req = urllib.request.Request(self.api_base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            raise self._api_error(raw) from exc
        except urllib.error.URLError as exc:
            raise ApiError("NETWORK_ERROR", "无法连接 BaseBuilder API，请检查网络或 API 地址。", retryable=True) from exc

        if raw == "":
            return {}
        payload = json.loads(raw)
        if isinstance(payload, dict) and payload.get("ok") is False:
            err = payload.get("error") or {}
            raise ApiError(str(err.get("code") or "API_ERROR"), str(err.get("message") or "请求失败。"), retryable=bool(err.get("retryable")))
        if isinstance(payload, dict) and payload.get("ok") is True:
            return payload.get("data") or {}
        if isinstance(payload, dict) and payload.get("success") is False:
            err = payload.get("error") or {}
            code = str(err.get("code") or payload.get("code") or "API_ERROR")
            retryable = bool(err.get("retryable")) or code == "429"
            raise ApiError(code, str(err.get("message") or payload.get("message") or "请求失败。"), retryable=retryable)
        if isinstance(payload, dict) and payload.get("success") is True:
            return payload.get("data") or {}
        if isinstance(payload, dict):
            return payload
        raise ApiError("API_RESPONSE_INVALID", "API 返回格式无法识别。")

    def _api_error(self, raw: str) -> ApiError:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return ApiError("API_ERROR", "API 请求失败。")
        err = payload.get("error") or {}
        return ApiError(str(err.get("code") or payload.get("code") or "API_ERROR"), str(err.get("message") or payload.get("message") or "API 请求失败。"), retryable=bool(err.get("retryable")))


def poll_for_token(client: BaseBuilderApiClient, device_code: str, expires_at: int, poll_interval: int) -> dict[str, Any]:
    while int(time.time()) < expires_at:
        result = client.device_poll(device_code)
        status = result.get("status")
        if status == "approved" and result.get("access_token"):
            return result
        if status in {"expired", "denied"}:
            raise ApiError("DEVICE_" + str(status).upper(), "登录请求未完成，请重新运行 `basebuilder login`。")
        time.sleep(max(1, int(result.get("poll_interval") or poll_interval or 5)))
    raise ApiError("DEVICE_EXPIRED", "登录请求已过期，请重新运行 `basebuilder login`。")


def _as_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    return dict(value)


def _is_terminal_snapshot(payload: dict[str, Any]) -> bool:
    candidates = _snapshot_candidates(payload)

    terminal = {
        "success",
        "succeeded",
        "completed",
        "complete",
        "failed",
        "failure",
        "error",
        "cancelled",
        "canceled",
        "killed",
        "interrupted",
        "denied",
        "expired",
    }
    active = {
        "running",
        "queued",
        "pending",
        "processing",
        "started",
        "in_progress",
        "retrying",
        "granted",
    }

    has_finalized_delivery = any(
        str(candidate.get("last_success_step") or candidate.get("lastSuccessStep") or "") == "fast_build.finalize"
        for candidate in candidates
    ) and any(_candidate_url(candidate) for candidate in candidates)
    if has_finalized_delivery:
        return True

    for candidate in candidates:
        for key in ("status", "state", "queue_state"):
            status = str(candidate.get(key) or "").strip().lower()
            if status in terminal:
                return True
            if status in active:
                return False

    for candidate in candidates:
        try:
            if float(candidate.get("progress") or 0) >= 100:
                return True
        except (TypeError, ValueError):
            continue

    return False


def _snapshot_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    stack = [payload]
    seen: set[int] = set()
    while stack and len(candidates) < 16:
        value = stack.pop(0)
        if not isinstance(value, dict) or id(value) in seen:
            continue
        seen.add(id(value))
        candidates.append(value)
        for key in ("data", "snapshot", "_runtime", "runtime", "delivery", "ready"):
            child = value.get(key)
            if isinstance(child, dict):
                stack.append(child)
    return candidates


def _candidate_url(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("baseUrl")
        or candidate.get("base_url")
        or candidate.get("app_url")
        or candidate.get("feishu_url")
        or candidate.get("url")
        or ""
    )
