from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import render_manual, sanitize_artifact
from .client import ApiError


REPORT_SCHEMA_VERSION = "basebuilder.report.v1"


def build_report(run_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
    safe = sanitize_artifact(artifact)
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "runId": run_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "base": safe.get("base") or {},
        "summary": safe.get("summary") or {},
        "tables": safe.get("tables") or [],
        "workflow": safe.get("workflow") or [],
        "copy": safe.get("copy"),
    }


def write_report(report: dict[str, Any], out: str | Path) -> Path:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize_artifact(report), ensure_ascii=False, indent=2))
    return path


def read_report(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ApiError("REPORT_INVALID", "report 必须是 JSON object。", retryable=False)
    if data.get("schemaVersion") != REPORT_SCHEMA_VERSION:
        raise ApiError("REPORT_VERSION_UNSUPPORTED", "report schemaVersion 不受支持。", retryable=False)
    return sanitize_artifact(data)


def render_report_markdown(report: dict[str, Any]) -> str:
    return render_manual(materialize_report_artifact(report))


def materialize_report_artifact(report: dict[str, Any]) -> dict[str, Any]:
    artifact = sanitize_artifact(report)
    copy = artifact.get("copy")
    if isinstance(copy, dict):
        copied_base = copy.get("base")
        if isinstance(copied_base, dict) and copied_base:
            base = dict(artifact.get("base") or {})
            base.update(copied_base)
            artifact["base"] = base
        artifact["tables"] = apply_copy_maps(artifact.get("tables") or [], copy)
    return artifact


def apply_copy_maps(tables: list[dict[str, Any]], copy: dict[str, Any]) -> list[dict[str, Any]]:
    table_map = copy.get("tableIdMap") if isinstance(copy.get("tableIdMap"), dict) else {}
    field_map = copy.get("fieldIdMap") if isinstance(copy.get("fieldIdMap"), dict) else {}
    view_map = copy.get("viewIdMap") if isinstance(copy.get("viewIdMap"), dict) else {}
    result = []
    for table in tables:
        item = dict(table)
        table_id = str(item.get("tableId") or item.get("table_id") or "")
        if table_id and table_id in table_map:
            item["originalTableId"] = table_id
            item["tableId"] = table_map[table_id]
        fields = []
        for field in item.get("fields") or []:
            field_item = dict(field)
            field_id = str(field_item.get("fieldId") or field_item.get("field_id") or "")
            if field_id and field_id in field_map:
                field_item["originalFieldId"] = field_id
                field_item["fieldId"] = field_map[field_id]
            fields.append(field_item)
        item["fields"] = fields
        views = []
        for view in item.get("views") or []:
            view_item = dict(view)
            view_id = str(view_item.get("viewId") or view_item.get("view_id") or "")
            if view_id and view_id in view_map:
                view_item["originalViewId"] = view_id
                view_item["viewId"] = view_map[view_id]
            views.append(view_item)
        item["views"] = views
        result.append(item)
    return result


def merge_copy_result(report_path: str | Path, copy_result_path: str | Path) -> dict[str, Any]:
    report = read_report(report_path)
    copy_result = json.loads(Path(copy_result_path).read_text())
    if not isinstance(copy_result, dict):
        raise ApiError("LARK_COPY_RESULT_INVALID", "copy-result 必须是 JSON object。", retryable=False)
    report["copy"] = sanitize_artifact(copy_result)
    write_report(report, report_path)
    return report


def require_larkcli() -> str:
    binary = shutil.which("larkcli") or shutil.which("lark-cli")
    if not binary:
        raise ApiError(
            "LARKCLI_NOT_FOUND",
            "未找到 larkcli/lark-cli。请先安装并登录本地 larkcli，或提供 --copy-result。",
            retryable=False,
        )
    return binary
