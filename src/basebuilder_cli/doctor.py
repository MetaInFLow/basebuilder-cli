from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .client import ApiError
from .config import CliConfig, DEFAULT_API_BASE, state_dir
from .runs import list_runs


CheckStatus = str


TERMINAL_STATUSES = {
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

ACTIVE_STATUSES = {
    "building",
    "running",
    "queued",
    "pending",
    "processing",
    "started",
    "in_progress",
    "retrying",
}

QUOTA_KEY_PRIORITY = (
    "remaining_base_count",
    "remainingbases",
    "remaining_base",
    "base_remaining",
    "remaining_count",
    "available_count",
    "available",
    "credits",
    "points",
    "balance",
    "remaining",
)


@dataclass
class DoctorOptions:
    max_runs: int = 5


def run_doctor(
    *,
    config: CliConfig,
    api_factory: Callable[[str, str], Any],
    options: DoctorOptions | None = None,
) -> dict[str, Any]:
    options = options or DoctorOptions()
    checks: list[dict[str, Any]] = []
    next_steps: list[str] = []
    api_ok = False
    auth_ok = False
    quota_blocked = False
    quota_unknown = False
    user_data: dict[str, Any] = {}
    quota_fields: list[dict[str, Any]] = []
    remaining_credits: int | float | None = None

    environment = {
        "apiBase": config.api_base,
        "stateDir": str(state_dir()),
        "configPath": str(state_dir() / "config.json"),
        "usesProductionApi": config.api_base == DEFAULT_API_BASE,
    }

    client = api_factory(config.api_base, config.token)

    try:
        capabilities = client.capabilities()
        api_ok = True
        checks.append(ok_check("api", f"BaseBuilder API 可连接: {config.api_base}", {"capabilities": capabilities}))
    except ApiError as exc:
        checks.append(error_check("api", exc, f"BaseBuilder API 连接失败: {exc}", network_steps(config.api_base)))
        next_steps.extend(network_steps(config.api_base))

    if not config.token:
        checks.append(fail_check(
            "auth",
            "本机还没有 BaseBuilder 登录凭据。",
            ["运行 `basebuilder login`，在浏览器里完成授权后再重试。"],
            {"code": "AUTH_TOKEN_MISSING"},
        ))
        if api_ok:
            next_steps.append("运行 `basebuilder login` 完成登录。")
    elif api_ok:
        try:
            user_data = client.me()
            auth_ok = True
            account_label = user_label(user_data)
            checks.append(ok_check("auth", f"登录有效: {account_label}", {"user": public_user(user_data)}))
        except ApiError as exc:
            checks.append(error_check("auth", exc, f"登录状态不可用: {exc}", auth_steps(exc.code)))
            next_steps.extend(auth_steps(exc.code))
    else:
        checks.append(warn_check(
            "auth",
            "由于 API 不可连接，暂时无法验证本机登录凭据。",
            ["先修复 API 连接，再运行 `basebuilder doctor`。"],
        ))

    if auth_ok:
        quota_fields = collect_quota_fields(user_data)
        remaining_credits = best_quota_value(quota_fields)
        if remaining_credits is None:
            quota_unknown = True
            checks.append(warn_check(
                "credits",
                "已登录，但当前 API 响应里没有可识别的剩余次数字段。",
                ["运行 `basebuilder whoami --format json` 查看账号详情；如无法看到次数，请到 Web 账户页确认。"],
                {"quotaFields": quota_fields},
            ))
        elif remaining_credits <= 0:
            quota_blocked = True
            checks.append(fail_check(
                "credits",
                "账号当前没有可用 BaseBuilder 构建次数。",
                ["打开 https://www.basebuilder.cn/account?tab=subscribe 充值或购买次数后再创建。"],
                {"remainingCredits": remaining_credits, "quotaFields": quota_fields},
            ))
            next_steps.append("打开 https://www.basebuilder.cn/account?tab=subscribe 充值或购买次数。")
        else:
            checks.append(ok_check(
                "credits",
                f"账号还有可用构建次数: {format_number(remaining_credits)}",
                {"remainingCredits": remaining_credits, "quotaFields": quota_fields},
            ))

    runs = diagnose_runs(client if auth_ok else None, max_runs=options.max_runs)
    if runs["running"]:
        checks.append(warn_check(
            "runs",
            f"检测到 {len(runs['running'])} 个本地记录中的运行中任务。",
            [f"运行 `basebuilder runs attach {runs['running'][0]['runId']}` 查看进度。"],
            runs,
        ))
        next_steps.append(f"运行 `basebuilder runs attach {runs['running'][0]['runId']}` 查看当前任务进度。")
    else:
        checks.append(ok_check("runs", "没有检测到本地仍在运行的任务。", runs))

    lark_binary = shutil.which("larkcli") or shutil.which("lark-cli")
    if lark_binary:
        checks.append(ok_check("larkcli", f"已找到本地 Lark CLI: {lark_binary}", {"path": lark_binary}))
    else:
        checks.append(warn_check(
            "larkcli",
            "未找到本地 larkcli / lark-cli；只有复制到自己 Lark 空间时才需要。",
            ["需要复制 Base 时，先安装并登录 larkcli，然后提供 copy-result.json。"],
        ))

    summary_status = "ready"
    usable = True
    message = "BaseBuilder CLI 当前可以使用。"

    if not api_ok:
        summary_status = "offline"
        usable = False
        message = "当前无法连接 BaseBuilder API。"
    elif not auth_ok:
        summary_status = "needs_login"
        usable = False
        message = "当前需要重新登录 BaseBuilder。"
    elif quota_blocked:
        summary_status = "no_credits"
        usable = False
        message = "当前账号没有可用构建次数。"
    elif quota_unknown:
        summary_status = "ready_with_warnings"
        usable = True
        message = "登录和 API 可用，但剩余次数无法从当前 API 响应确认。"

    next_steps = dedupe(next_steps)
    if not next_steps and runs["running"]:
        next_steps = [f"运行 `basebuilder runs attach {runs['running'][0]['runId']}` 查看当前任务进度。"]
    if not next_steps and usable:
        next_steps = ["可以运行 `basebuilder create --input input.json --format ndjson` 创建多维表。"]

    return {
        "summary": {
            "status": summary_status,
            "usable": usable,
            "message": message,
            "nextSteps": next_steps,
        },
        "environment": environment,
        "account": {
            "loggedIn": auth_ok,
            "userLabel": user_label(user_data) if auth_ok else "",
            "remainingCredits": remaining_credits,
            "quotaFields": quota_fields,
        },
        "runs": runs,
        "checks": checks,
    }


def diagnose_runs(client: Any | None, *, max_runs: int) -> dict[str, Any]:
    latest: list[dict[str, Any]] = []
    running: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for run in list_runs()[:max(0, max_runs)]:
        run_id = str(run.get("run_id") or run.get("runId") or "")
        if not run_id:
            continue
        status = str(run.get("status") or "").strip().lower()
        item: dict[str, Any] = {
            "runId": run_id,
            "localStatus": status,
        }
        if client is not None and status not in TERMINAL_STATUSES:
            try:
                snapshot = client.run_snapshot(run_id)
                snapshot_status = snapshot_status_text(snapshot)
                item["snapshotStatus"] = snapshot_status
                item["progress"] = snapshot_progress(snapshot)
                item["currentStep"] = snapshot_current_step(snapshot)
                status = snapshot_status or status
            except ApiError as exc:
                errors.append({"runId": run_id, "code": exc.code, "message": str(exc)})
                item["snapshotError"] = {"code": exc.code, "message": str(exc)}
        latest.append(item)
        if status in ACTIVE_STATUSES:
            running.append(item)

    return {"latest": latest, "running": running, "errors": errors}


def render_doctor_human(report: dict[str, Any]) -> str:
    lines = [
        "BaseBuilder CLI Doctor",
        f"状态: {report['summary']['status']} - {report['summary']['message']}",
        f"API: {report['environment']['apiBase']}",
        f"本地状态目录: {report['environment']['stateDir']}",
        "",
        "检查项:",
    ]
    for check in report.get("checks", []):
        label = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}.get(str(check.get("status")), str(check.get("status")))
        lines.append(f"- [{label}] {check.get('id')}: {check.get('message')}")
        for step in check.get("nextSteps") or []:
            lines.append(f"  next: {step}")
    next_steps = report.get("summary", {}).get("nextSteps") or []
    if next_steps:
        lines.extend(["", "下一步:"])
        lines.extend(f"- {step}" for step in next_steps)
    return "\n".join(lines)


def ok_check(check_id: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": check_id, "status": "ok", "message": message, "details": details or {}, "nextSteps": []}


def warn_check(
    check_id: str,
    message: str,
    next_steps: list[str],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"id": check_id, "status": "warn", "message": message, "details": details or {}, "nextSteps": next_steps}


def fail_check(
    check_id: str,
    message: str,
    next_steps: list[str],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"id": check_id, "status": "fail", "message": message, "details": details or {}, "nextSteps": next_steps}


def error_check(check_id: str, exc: ApiError, message: str, next_steps: list[str]) -> dict[str, Any]:
    return fail_check(
        check_id,
        message,
        next_steps,
        {"code": exc.code, "retryable": exc.retryable},
    )


def network_steps(api_base: str) -> list[str]:
    steps = ["检查网络连接，确认可以访问 https://www.basebuilder.cn。"]
    if api_base != DEFAULT_API_BASE:
        steps.append("当前使用了非生产 API；确认 `BB_API_BASE` 或 `--api-base` 是否写错。")
    else:
        steps.append("如果你在本地开发，请显式使用 `--api-base http://127.0.0.1:8999`。")
    return steps


def auth_steps(code: str) -> list[str]:
    normalized = code.upper()
    if normalized in {"AUTH_REVOKED", "AUTH_EXPIRED", "UNAUTHORIZED", "401"}:
        return ["运行 `basebuilder login` 重新授权。"]
    return ["运行 `basebuilder login` 重新登录；如果仍失败，先运行 `basebuilder doctor --format json` 保留诊断输出。"]


def collect_quota_fields(value: Any, prefix: str = "") -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            lower = str(key).lower()
            if isinstance(nested, (int, float)) and not isinstance(nested, bool) and is_quota_key(lower):
                fields.append({"path": path, "value": nested})
            fields.extend(collect_quota_fields(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value[:20]):
            fields.extend(collect_quota_fields(nested, f"{prefix}[{index}]"))
    return fields


def is_quota_key(lower_key: str) -> bool:
    normalized = lower_key.replace("-", "_")
    if normalized in QUOTA_KEY_PRIORITY:
        return True
    return any(token in normalized for token in ("remaining_base", "remaining_count", "available_count", "credits", "points"))


def best_quota_value(fields: list[dict[str, Any]]) -> int | float | None:
    if not fields:
        return None
    ranked = sorted(fields, key=lambda item: quota_rank(str(item.get("path") or "")))
    value = ranked[0].get("value")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def quota_rank(path: str) -> int:
    lower = path.lower().replace("-", "_")
    for index, key in enumerate(QUOTA_KEY_PRIORITY):
        if key in lower:
            return index
    return len(QUOTA_KEY_PRIORITY)


def user_label(data: dict[str, Any]) -> str:
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    for key in ("nickname", "name", "email", "phone", "id"):
        value = user.get(key) if isinstance(user, dict) else None
        if value not in (None, ""):
            return str(value)
    return "已登录用户"


def public_user(data: dict[str, Any]) -> dict[str, Any]:
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    if not isinstance(user, dict):
        return {}
    return {key: user[key] for key in ("id", "nickname", "name", "email", "phone") if key in user}


def snapshot_status_text(snapshot: dict[str, Any]) -> str:
    for candidate in snapshot_candidates(snapshot):
        for key in ("status", "state", "queue_state"):
            value = str(candidate.get(key) or "").strip().lower()
            if value:
                return value
    return ""


def snapshot_progress(snapshot: dict[str, Any]) -> Any:
    for candidate in snapshot_candidates(snapshot):
        if candidate.get("progress") not in (None, ""):
            return candidate.get("progress")
    return None


def snapshot_current_step(snapshot: dict[str, Any]) -> str:
    for candidate in snapshot_candidates(snapshot):
        for key in ("currentStep", "current_step", "step"):
            value = str(candidate.get(key) or "").strip()
            if value:
                return value
    return ""


def snapshot_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    stack: list[Any] = [snapshot]
    while stack:
        value = stack.pop(0)
        if not isinstance(value, dict):
            continue
        result.append(value)
        for key in ("data", "snapshot", "delivery"):
            nested = value.get(key)
            if isinstance(nested, dict):
                stack.append(nested)
    return result


def dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def format_number(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
