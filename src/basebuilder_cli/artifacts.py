from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path
from typing import Any


SENSITIVE_KEY_FRAGMENTS = [
    "token",
    "cookie",
    "secret",
    "password",
    "authorization",
    "answer_text",
    "problem_text",
    "raw",
    "raw_prompt",
    "raw_log",
]


def write_manual(artifact: dict[str, Any], out: str | Path) -> Path:
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe = sanitize_artifact(artifact)
    out_path.write_text(render_manual(safe))
    return out_path


def write_skill(artifact: dict[str, Any], out_dir: str | Path) -> Path:
    root = Path(out_dir)
    if root.exists():
        shutil.rmtree(root)
    refs = root / "references"
    refs.mkdir(parents=True, exist_ok=True)

    safe = sanitize_artifact(artifact)
    (root / "SKILL.md").write_text(render_skill(safe))
    (refs / "base-schema.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2))
    (refs / "usage-manual.md").write_text(render_manual(safe))
    return root


def render_manual(artifact: dict[str, Any]) -> str:
    base = artifact.get("base") or {}
    summary = artifact.get("summary") or {}
    tables = artifact.get("tables") or []
    workflow = normalize_workflow(artifact.get("workflow"))

    lines = [
        f"# {base.get('name') or 'BaseBuilder 生成系统'} 使用说明书",
        "",
        "## 访问",
        "",
        f"- Base URL: {base.get('url') or '未提供'}",
        f"- 表数量: {summary.get('tables', len(tables))}",
        f"- 字段数量: {summary.get('fields', count_fields(tables))}",
        f"- 视图数量: {summary.get('views', count_views(tables))}",
        "",
        "## 使用流程",
        "",
    ]
    for index, step in enumerate(workflow or ["查看表结构", "录入必要字段", "按视图跟进状态"], start=1):
        lines.append(f"{index}. {step}")

    lines.extend(["", "## 表、字段与视图", ""])
    for table in tables:
        lines.extend([
            f"### {table.get('name') or '未命名表'}",
            "",
            table.get("description") or "用于承载该业务环节的数据。",
            "",
            "| 字段 | 类型 | 说明 |",
            "| --- | --- | --- |",
        ])
        for field in table.get("fields") or []:
            lines.append(f"| {field.get('name') or ''} | {field.get('type') or ''} | {field.get('description') or ''} |")
        views = table.get("views") or []
        if views:
            lines.extend(["", "视图："])
            for view in views:
                lines.append(f"- {view.get('name') or ''}: {view.get('type') or ''}")
        lines.append("")

    lines.extend([
        "## 本地文件提醒",
        "",
        "本文件可能包含 Base 链接和业务字段结构，请只保存在可信目录。",
        "",
    ])
    return "\n".join(lines)


def render_skill(artifact: dict[str, Any]) -> str:
    base = artifact.get("base") or {}
    tables = artifact.get("tables") or []
    table_names = "、".join(str(table.get("name") or "") for table in tables if table.get("name"))
    skill_name = generated_skill_name(artifact)

    lines = [
        "---",
        f"name: {skill_name}",
        "description: Use when operating this specific generated BaseBuilder Base, including reading, adding, updating records, or explaining table and view workflows.",
        "---",
        "",
        f"# {base.get('name') or 'BaseBuilder 生成系统'} Agent Skill",
        "",
        "## When To Use",
        "",
        f"当用户需要查询、补录、更新或解释 `{base.get('name') or '该 Base'}` 中的数据时使用本 Skill。",
        "",
        "## Prerequisites",
        "",
        "- 用户已拥有目标 Base 的访问权限。",
        "- 操作前先读取 `references/base-schema.json` 和 `references/usage-manual.md`。",
        "- 本 Skill 不包含登录凭据、浏览器会话、飞书密钥或原始日志。",
        "",
        "## Base Summary",
        "",
        f"- Base URL: {base.get('url') or '未提供'}",
        f"- 核心表: {table_names or '见 schema'}",
        "",
        "## Tables, Fields, And Views",
        "",
    ]
    for table in tables:
        fields = table.get("fields") or []
        views = table.get("views") or []
        lines.append(f"### {table.get('name') or '未命名表'}")
        description = str(table.get("description") or "").strip()
        if description:
            lines.append(description)
        if fields:
            lines.append("")
            lines.append("字段：")
            for field in fields:
                field_name = field.get("name") or ""
                field_type = field.get("type") or "unknown"
                field_desc = field.get("description") or ""
                suffix = f" - {field_desc}" if field_desc else ""
                lines.append(f"- {field_name} ({field_type}){suffix}")
        if views:
            lines.append("")
            lines.append("视图：")
            for view in views:
                lines.append(f"- {view.get('name') or ''}: {view.get('type') or ''}")
        lines.append("")

    lines.extend([
        "## Safe Write Rules",
        "",
        "- 查询和只读汇总可以直接执行。",
        "- 新增、修改、删除记录前，必须向用户复述目标表、字段和值。",
        "- 高风险写入必须先获得用户明确确认，包括批量改动、删除、覆盖关键状态、影响财务或客户字段的操作。",
        "- 不要写入 schema 中不存在的字段。",
        "",
        "## Operation Examples",
        "",
        "- 查询：按用户给定条件读取相关表和视图。",
        "- 新增：确认目标表和必填字段后创建记录。",
        "- 更新：先读取当前记录，再说明将变化的字段，确认后写入。",
        "",
        "## Known Limitations",
        "",
        "- 字段和视图以生成时的 schema 为准；如果 Base 已被人工调整，先重新读取实际结构。",
        "- 无法确认权限或业务影响时，停止并询问用户。",
        "",
    ])
    return "\n".join(lines)


def generated_skill_name(artifact: dict[str, Any]) -> str:
    stable = json.dumps(sanitize_artifact(artifact), ensure_ascii=True, sort_keys=True)
    digest = hashlib.sha256(stable.encode()).hexdigest()[:10]
    return f"basebuilder-base-{digest}"


def sanitize_artifact(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS):
                continue
            clean[key] = sanitize_artifact(item)
        return clean
    if isinstance(value, list):
        return [sanitize_artifact(item) for item in value]
    return value


def count_fields(tables: list[dict[str, Any]]) -> int:
    return sum(len(table.get("fields") or []) for table in tables)


def count_views(tables: list[dict[str, Any]]) -> int:
    return sum(len(table.get("views") or []) for table in tables)


def normalize_workflow(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        steps = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(item.get("name") or item.get("title") or item.get("step") or item.get("description") or "").strip()
            else:
                text = str(item).strip()
            if text:
                steps.append(text)
        return steps
    return []
