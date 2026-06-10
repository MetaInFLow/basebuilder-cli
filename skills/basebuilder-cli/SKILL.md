---
name: basebuilder-cli
description: Use when an agent needs to use BaseBuilder CLI to log in, register an agent device, create BaseBuilder multi-dimensional tables, inspect runs, or generate manual and per-Base Skill artifacts.
---

# BaseBuilder CLI

## Overview

使用 `basebuilder` 作为 BaseBuilder 用户工作流的唯一命令行入口。用户态 AI 请求必须进入 `https://www.basebuilder.cn` 背后的产品 API；不要直连 Builder 服务。

## Install Or Verify

```bash
python3 -m pip install --user git+https://github.com/MetaInFLow/basebuilder-cli.git
basebuilder health --format json
```

如果需要隔离安装，优先使用：

```bash
pipx install git+https://github.com/MetaInFLow/basebuilder-cli.git
```

生产环境不需要配置 `BB_API_BASE`。只有明确做本地 smoke 时，才允许用 `BB_API_BASE` 或 `--api-base` 指向 `http://127.0.0.1:8999`。

## Login And Agent Registration

- 人类用户登录：`basebuilder login`
- Agent 设备注册：`basebuilder agent register`
- 查看当前用户：`basebuilder whoami --format json`
- 查看 Agent 状态：`basebuilder agent status --format json`
- 退出并吊销本地 token：`basebuilder logout`

浏览器授权页成功后可能会自动关闭，但登录是否完成只以 CLI 收到并保存 access token 为准。

## Create A Base

Agent 调用时优先使用结构化输出：

```bash
basebuilder create --prompt "用户的业务系统需求" --format ndjson
```

用户确认三要素前不要使用 `--auto-accept`，除非用户明确要求跳过 review。非交互自动化里，先展示拆解出的管理对象、流程和字段，拿到确认后再继续。

多输入模式：

```bash
basebuilder create --input input.json --format ndjson
basebuilder create --mode excel --file workbook.xlsx --format ndjson
basebuilder create --mode excel --file data.csv --format ndjson
```

`--mode excel` 表示表格结构是 source of truth；普通需求带文件时使用 `--mode text --file spec.md`，文件只是背景上下文。

## Resume And Artifacts

```bash
basebuilder runs list --format json
basebuilder runs inspect <run_id> --format json
basebuilder runs attach <run_id> --format ndjson
basebuilder report generate <run_id> --out ./report.json
basebuilder report render <run_id> --report ./report.json --out ./report.md
basebuilder artifacts manual <run_id> --from-report ./report.json --out ./manual.md
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
```

生成的 `base-skill` 是操作该具体 Base 的 per-Base Skill。读取或写入该 Base 记录前，先加载这个 Skill。

## Lark Copy

复制到用户自己的 Lark 空间由本地 `larkcli` / `lark-cli` 负责登录和授权，BaseBuilder CLI 不保存 Lark 凭据。复制完成后，把 id map 合并进 report：

```bash
basebuilder lark copy <run_id> --report ./report.json --copy-result ./copy-result.json
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
```

如果缺少 `larkcli` 或 copy result，停止并让用户完成本地交互式复制。不要猜测 Base/table/field/view id。

## Safety Rules

- 不要提交 `~/.basebuilder`、access token、cookie、浏览器 session、生成的客户数据或临时 smoke 产物。
- 只读查询可以通过生成的 per-Base Skill 直接执行。
- 新增、更新、删除或批量修改记录前，必须复述目标表、字段和值，并等待用户明确确认。
- run 中断时先用 `runs inspect` 或 `runs attach` 恢复；不要在未确认的情况下重复发起构建。
