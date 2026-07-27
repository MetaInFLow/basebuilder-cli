---
name: basebuilder-cli
description: Use when a user wants BaseBuilder to turn a business workflow, spreadsheet, role/scenario/pain-point template, existing files, or operating process into a multidimensional business base.
---

# BaseBuilder CLI

Use `basebuilder` as the only command-line entry for BaseBuilder user workflows. User-facing AI requests must go through `https://www.basebuilder.cn`; do not call Builder directly.

## Version Check First

Every time this Skill is loaded, make version checking the first action. Before any `basebuilder` command, login, diagnosis, or build, run:

```bash
python3 <skill-directory>/scripts/check_version.py
```

Resolve `<skill-directory>` to the directory containing this `SKILL.md`; do not execute the placeholder literally. Check only once per user task.

- `up_to_date`: continue with `doctor`.
- `update_available`: report the installed and latest releases, upgrade to the latest stable tag with the original installation method, reinstall this Skill with `basebuilder skill install --target <current-target>`, and rerun the check before continuing. Continue on the old version only when the user explicitly asks to do so, and disclose the risk.
- `ahead_of_release`: identify the installation as a development build and continue without downgrading it.
- `editable_source_differs`: report the local and remote commits. Do not overwrite a development branch or uncommitted changes.
- `not_installed`: follow the installation flow below.
- `unknown` or `check_failed`: disclose that the latest version could not be confirmed. A network check failure does not block the current business task.

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
