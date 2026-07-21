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

The AI方案初稿/三要素 result must be shown to the user and explicitly confirmed before generation. When `create` returns `confirmationRequired=true`, keep its draft `runId`. After the user confirms, resume that exact draft:

```bash
basebuilder create confirm <draft-run-id> --format json
```

Do not run `create` or `create --auto-accept` again after confirmation. `confirm` must reuse the draft's `message_id`, `task_id`, and elements without another analyze request. If confirm fails, do not fall back to creating a new task. Use `--auto-accept` only when the user explicitly authorizes trusted automation to skip review from the beginning.

The build start uses an asynchronous JSON protocol and does not consume generation SSE. Keep the canonical `runId` returned by confirm or trusted automation and use `runs inspect` for authoritative server status. Wait on `queued/running/retrying`; finish only on `succeeded`; stop on `failed/timed_out/cancelled/interrupted`. If status is `unknown`, do not create another task. Local run files are handles only and must never override server state.

After generation, ask the user to inspect the Base URL. Only after they approve, run Lark copy and merge `copy-result.json` into the report. Then ask whether the agent should learn the table; if yes, generate and install the per-Base Skill.
