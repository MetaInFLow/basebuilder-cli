from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .client import ApiError


SUPPORTED_MODES = {"text", "excel"}


TEMPLATE_FIELD_ALIASES = {
    "wantToBuild": ("wantToBuild", "want_to_build", "title", "我想要构建", "想要构建", "我要构建", "构建目标"),
    "role": ("role", "persona", "team", "我是", "我们是", "用户身份", "团队角色"),
    "scenario": ("scenario", "business_scenario", "current_process", "currentWorkflow", "业务场景", "当前流程", "使用场景"),
    "painPoints": ("painPoints", "pain_points", "pains", "pain", "痛点", "问题", "当前痛点"),
    "existingMaterials": ("existingMaterials", "existing_materials", "materials", "已有资料", "已有材料", "资料"),
    "desiredOutputs": ("desiredOutputs", "desired_outputs", "goals", "outputs", "希望输出", "目标", "期望产出"),
    "constraints": ("constraints", "limits", "约束", "限制", "不做"),
    "examples": ("examples", "samples", "参考案例", "例子"),
    "background": ("background", "背景", "补充背景"),
}

LIST_TEMPLATE_FIELDS = {"painPoints", "desiredOutputs", "constraints", "examples"}


def build_intake_prompt(
    *,
    prompt: str,
    mode: str = "text",
    input_path: str = "",
    files: list[str] | None = None,
    structured_input: dict[str, Any] | None = None,
) -> str:
    payload = build_intake_payload(
        prompt=prompt,
        mode=mode,
        input_path=input_path,
        files=files,
        structured_input=structured_input,
    )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_intake_payload(
    *,
    prompt: str,
    mode: str = "text",
    input_path: str = "",
    files: list[str] | None = None,
    structured_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = files or []
    structured: dict[str, Any] = dict(structured_input or {})
    if input_path:
        structured = {**structured, **load_structured_input(Path(input_path))}
        mode = str(structured.get("mode") or mode or "text")
    mode = normalize_mode(mode)

    template = normalize_template_input(structured)
    freeform = prompt.strip()
    if freeform:
        template["freeformBrief"] = freeform
    file_payloads = [summarize_file(Path(path), mode=mode) for path in files]
    if mode == "excel" and not any(file.get("type") in {"csv", "xlsx"} for file in file_payloads):
        raise ApiError("INTAKE_EXCEL_FILE_REQUIRED", "Excel 模式至少需要一个 .csv 或 .xlsx 文件。", retryable=False)

    if not any(value for value in template.values()) and not file_payloads:
        raise ApiError("INTAKE_EMPTY", "请输入需求，或提供 --input / --file。", retryable=False)

    return {
        "schemaVersion": "basebuilder.intake.v1",
        "mode": mode,
        "sourceTruth": "uploaded_spreadsheets" if mode == "excel" else "template_and_context",
        "intakeTemplate": template,
        "files": file_payloads,
    }


def build_refine_instruction(
    *,
    instruction: str,
    files: list[str] | None = None,
    mode: str = "text",
) -> str:
    files = files or []
    if not files:
        return instruction
    normalized_mode = normalize_mode(mode)
    payload = {
        "schemaVersion": "basebuilder.three_elements_refine.v1",
        "instruction": instruction,
        "mode": normalized_mode,
        "files": [summarize_file(Path(path), mode=normalized_mode) for path in files],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def normalize_mode(mode: str) -> str:
    value = str(mode or "text").strip().lower()
    if value not in SUPPORTED_MODES:
        raise ApiError("INTAKE_MODE_UNSUPPORTED", f"暂不支持输入模式: {mode}", retryable=False)
    return value


def load_structured_input(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ApiError("INPUT_FILE_NOT_FOUND", f"输入文件不存在: {path}", retryable=False)
    suffix = path.suffix.lower()
    if suffix != ".json":
        raise ApiError("INPUT_FORMAT_UNSUPPORTED", "当前 CLI 仅支持 JSON 结构化输入。", retryable=False)
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ApiError("INPUT_FORMAT_INVALID", "结构化输入必须是 JSON object。", retryable=False)
    return data


def normalize_template_input(data: dict[str, Any]) -> dict[str, Any]:
    template: dict[str, Any] = {}
    for field, aliases in TEMPLATE_FIELD_ALIASES.items():
        value = first_present(data, aliases)
        if field in LIST_TEMPLATE_FIELDS:
            values = normalize_list(value)
            if values:
                template[field] = values
            continue
        text = normalize_text(value)
        if text:
            template[field] = text
    return template


def first_present(data: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in data and data[key] not in (None, "", []):
            return data[key]
    return None


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False, sort_keys=True)]
    text = str(value).strip()
    if not text:
        return []
    parts = text.replace("；", ",").replace("，", ",").replace("\n", ",").split(",")
    return [part.strip() for part in parts if part.strip()]


def summarize_file(path: Path, *, mode: str) -> dict[str, Any]:
    if not path.exists():
        raise ApiError("INTAKE_FILE_NOT_FOUND", f"文件不存在: {path}", retryable=False)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return summarize_csv(path, mode=mode)
    if suffix == ".xlsx":
        return summarize_xlsx(path, mode=mode)
    if suffix in {".txt", ".md", ".markdown"}:
        text = path.read_text(errors="ignore").strip()
        excerpt = text[:2000]
        return {
            "fileName": path.name,
            "type": "text",
            "sourceRole": "supporting_context",
            "excerpt": excerpt,
        }
    raise ApiError("INTAKE_FILE_UNSUPPORTED", f"暂不支持该文件类型: {path.name}", retryable=False)


def summarize_csv(path: Path, *, mode: str) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    header = rows[0] if rows else []
    row_count = max(0, len(rows) - 1)
    return {
        "fileName": path.name,
        "type": "csv",
        "sourceRole": "schema_source" if mode == "excel" else "supporting_context",
        "columns": len(header),
        "headers": header,
        "rowCount": row_count,
        "sampleRows": rows[1:4],
    }


def summarize_xlsx(path: Path, *, mode: str) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        sheet_files = sorted(name for name in names if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        shared_strings = read_shared_strings(archive) if "xl/sharedStrings.xml" in names else []
        sheet_summaries = []
        for sheet_file in sheet_files[:5]:
            root = ET.fromstring(archive.read(sheet_file))
            dimension = ""
            dim_node = root.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}dimension")
            if dim_node is not None:
                dimension = str(dim_node.attrib.get("ref") or "")
            headers = first_row_values(root, shared_strings)
            sheet_summaries.append({
                "sheet": Path(sheet_file).stem,
                "dimension": dimension,
                "headers": headers,
            })
    return {
        "fileName": path.name,
        "type": "xlsx",
        "sourceRole": "schema_source" if mode == "excel" else "supporting_context",
        "sheets": sheet_summaries,
    }


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
        text_parts = [node.text or "" for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")]
        values.append("".join(text_parts))
    return values


def first_row_values(root: ET.Element, shared_strings: list[str]) -> list[str]:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    sheet_data = root.find(ns + "sheetData")
    if sheet_data is None:
        return []
    row = sheet_data.find(ns + "row")
    if row is None:
        return []
    values: list[str] = []
    for cell in row.findall(ns + "c")[:20]:
        cell_type = cell.attrib.get("t")
        value_node = cell.find(ns + "v")
        if value_node is None:
            values.append("")
            continue
        raw = value_node.text or ""
        if cell_type == "s":
            try:
                values.append(shared_strings[int(raw)])
            except (ValueError, IndexError):
                values.append(raw)
        else:
            values.append(raw)
    return values
