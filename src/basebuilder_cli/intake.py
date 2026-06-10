from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .client import ApiError


SUPPORTED_MODES = {"text", "excel"}


def build_intake_prompt(
    *,
    prompt: str,
    mode: str = "text",
    input_path: str = "",
    files: list[str] | None = None,
) -> str:
    files = files or []
    structured: dict[str, Any] = {}
    if input_path:
        structured = load_structured_input(Path(input_path))
        mode = str(structured.get("mode") or mode or "text")
    mode = normalize_mode(mode)

    parts = [
        "【BaseBuilder CLI Intake】",
        f"mode={mode}",
    ]
    if mode == "excel":
        parts.append("source of truth: uploaded spreadsheet structure")
    elif files:
        parts.append("file context: supporting background only, not schema source of truth")

    if prompt.strip():
        parts.extend(["", "【用户输入】", prompt.strip()])
    if structured:
        parts.extend(["", "【结构化输入】", render_structured_input(structured)])

    summaries = [summarize_file(Path(path), mode=mode) for path in files]
    if summaries:
        parts.extend(["", "【文件摘要】", "\n\n".join(summaries)])

    if len(parts) <= 2:
        raise ApiError("INTAKE_EMPTY", "请输入需求，或提供 --input / --file。", retryable=False)
    return "\n".join(parts).strip()


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


def render_structured_input(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in ("title", "scenario", "role", "background"):
        value = data.get(key)
        if value:
            lines.append(f"{key}: {value}")
    for key in ("goals", "constraints", "examples"):
        values = data.get(key)
        if isinstance(values, list) and values:
            lines.append(f"{key}:")
            for value in values:
                lines.append(f"- {value}")
    return "\n".join(lines) or json.dumps(data, ensure_ascii=False, indent=2)


def summarize_file(path: Path, *, mode: str) -> str:
    if not path.exists():
        raise ApiError("INTAKE_FILE_NOT_FOUND", f"文件不存在: {path}", retryable=False)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return summarize_csv(path, mode=mode)
    if suffix == ".xlsx":
        return summarize_xlsx(path)
    if suffix in {".txt", ".md", ".markdown"}:
        text = path.read_text(errors="ignore").strip()
        excerpt = text[:2000]
        return f"file={path.name}\ntype=text\nexcerpt:\n{excerpt}"
    raise ApiError("INTAKE_FILE_UNSUPPORTED", f"暂不支持该文件类型: {path.name}", retryable=False)


def summarize_csv(path: Path, *, mode: str) -> str:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    header = rows[0] if rows else []
    row_count = max(0, len(rows) - 1)
    lines = [
        f"file={path.name}",
        "type=csv",
        f"mode={mode}",
        f"columns={len(header)}",
        "headers=" + ", ".join(header),
        f"sampleRows={min(row_count, 3)}",
    ]
    for row in rows[1:4]:
        lines.append("sample=" + ", ".join(row))
    return "\n".join(lines)


def summarize_xlsx(path: Path) -> str:
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
    lines = [f"file={path.name}", "type=xlsx", "mode=excel", "source of truth: workbook structure"]
    for sheet in sheet_summaries:
        lines.append(f"sheet={sheet['sheet']} dimension={sheet['dimension']} headers={', '.join(sheet['headers'])}")
    return "\n".join(lines)


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
