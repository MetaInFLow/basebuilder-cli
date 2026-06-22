---
name: basebuilder-cli
description: Use when a user wants BaseBuilder to turn a business workflow, spreadsheet, role/scenario/pain-point template, existing files, or operating process into a multidimensional business base.
---

# BaseBuilder CLI

Use `basebuilder` as the only command-line entry for BaseBuilder user workflows. User-facing AI requests must go through `https://www.basebuilder.cn`; do not call Builder directly.

## Quick Start

```bash
basebuilder doctor --format json
basebuilder login
basebuilder create --input input.json --format ndjson
```

After `basebuilder login`, the CLI registers the local agent identity automatically. Do not ask the user to approve another agent registration page unless `doctor` or `agent status` says the token is missing or revoked.

## Create Rules

Before calling `basebuilder create`, extract structured intake from the user's words, files, and context into the Web first-page fields. Required fields: `我想要构建`, `我是`, `主要使用者`, `业务背景`, `核心痛点`, `已有资料`, `希望输出`, `背景知识`. If any required field is missing, ask the user to fill it first. If the user explicitly has no content for a field, write `暂无`; do not invent values.

Use structured intake matching the Web first page. Keep fields separate; do not collapse the fields into one natural-language prompt.

The AI方案初稿/三要素 result must be shown to the user and explicitly confirmed before generation. 三要素 is streamed; only proceed when `管理对象 / manage_what`, `流程 / workflow`, and `字段 / fields` are all non-empty. If the CLI returns `stage=ai_blueprint_streaming`, `status=analyzing`, or any element is empty, wait/retry instead of manually filling the missing elements and accepting. Do not use `--auto-accept` unless the user explicitly requested trusted automation.

After generation, ask the user to inspect the Base URL. Only after they approve, run Lark copy and merge `copy-result.json` into the report. Then ask whether the agent should learn the table; if yes, generate and install the per-Base Skill.
