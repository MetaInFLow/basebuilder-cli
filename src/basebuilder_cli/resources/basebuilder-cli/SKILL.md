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
basebuilder create --input input.json --format json
```

After `basebuilder login`, the CLI registers the local agent identity automatically. Do not ask the user to approve another agent registration page unless `doctor` or `agent status` says the token is missing or revoked.

## Create Rules

Use structured intake matching the Web first page. Keep fields separate: `我想要构建`, `我是`, `主要使用者`, `业务背景`, `核心痛点`, `已有资料`, `希望输出`, `背景知识`.

The AI方案初稿/三要素 result must be shown to the user and explicitly confirmed before generation. Do not use `--auto-accept` unless the user explicitly requested trusted automation.

`create` uses an asynchronous JSON start protocol and does not consume generation SSE. Keep the returned `runId` and use `runs inspect` for authoritative server status. Wait on `queued/running/retrying`; finish only on `succeeded`; stop on `failed/timed_out/cancelled/interrupted`. If status is `unknown`, do not create another task. Local run files are handles only and must never override server state.

After generation, ask the user to inspect the Base URL. Only after they approve, run Lark copy and merge `copy-result.json` into the report. Then ask whether the agent should learn the table; if yes, generate and install the per-Base Skill.
