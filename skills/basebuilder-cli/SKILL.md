---
name: basebuilder-cli
description: Use when a user wants BaseBuilder to turn a business workflow, spreadsheet, role/scenario/pain-point template, existing files, or operating process into a multidimensional business base.
---

# BaseBuilder CLI

## Overview

使用 `basebuilder` 作为 BaseBuilder 用户工作流的唯一命令行入口。触发条件是用户要把业务流程、Excel/CSV、角色/场景/痛点模版或已有资料转成可运营的多维业务表。用户态 AI 请求必须进入 `https://www.basebuilder.cn` 背后的产品 API；不要直连 Builder 服务。

## Install Or Verify

```bash
python3 -m pip install --user git+https://github.com/MetaInFLow/basebuilder-cli.git
basebuilder doctor --format json
basebuilder skill install --target codex
```

如果需要隔离安装，优先使用：

```bash
pipx install git+https://github.com/MetaInFLow/basebuilder-cli.git
basebuilder skill install --target codex
```

生产环境不需要配置 `BB_API_BASE`。只有明确做本地 smoke 时，才允许用 `BB_API_BASE` 或 `--api-base` 指向 `http://127.0.0.1:8999`。

## Login And Agent Registration

- 人类用户登录并自动完成本机 Agent 注册：`basebuilder login`
- Agent token 异常时重新注册：`basebuilder agent register`
- 诊断当前是否可用：`basebuilder doctor --format json`
- 查看当前用户：`basebuilder whoami --format json`
- 查看 Agent 状态：`basebuilder agent status --format json`
- 退出并吊销本地 token：`basebuilder logout`

浏览器授权页成功后可能会自动关闭，但登录是否完成只以 CLI 收到并保存 access token 为准。登录成功后 CLI 会用刚拿到的人类 CLI token 自动 upsert 本机 agent identity，不要再要求用户确认第二个 agent 注册页面。

## Doctor First

遇到连接失败、登录失败、次数不足、任务疑似还在跑、run attach 失败或用户不确定下一步时，先运行：

```bash
basebuilder doctor --format json
```

根据 `summary.status` 决策：

- `ready`: 可以继续 `create`；如果 `runs.running` 非空，先 `basebuilder runs inspect <run_id> --format json` 读取服务器状态。
- `needs_login`: 运行 `basebuilder login` 或 `basebuilder agent register`。
- `offline`: 检查网络、`BB_API_BASE`、`--api-base`，生产应为 `https://www.basebuilder.cn`。
- `no_credits`: 打开 Web 账户页充值或购买次数后再创建。
- `ready_with_warnings`: API 和登录可用，但还有非阻塞问题，按 `summary.nextSteps` 处理。

## Create A Base

Agent 调用时优先使用结构化输入，不要把首页的一组字段拼成一句大 prompt。结构化 `input.json` 应贴近 GUI 首屏模版：

```json
{
  "mode": "text",
  "我想要构建": "客户成功续费跟进系统",
  "我是": "客户成功团队负责人",
  "主要使用者": "客户成功经理、销售主管",
  "业务背景": "续费前 90 天识别风险并跟进",
  "核心痛点": ["风险靠人工记忆", "跟进动作散落在聊天记录"],
  "已有资料": "历史客户清单、续费记录、服务备注",
  "希望输出": ["客户健康度视图", "高风险续费跟进表"],
  "背景知识": "企业客户续费通常需要提前识别使用率下降、关键人变更和商务风险。"
}
```

```bash
basebuilder create --input input.json --format json
```

如果返回 `confirmationRequired=true`，这个 `runId` 是待确认草稿句柄。先向用户展示三要素，得到明确确认后运行：

```bash
basebuilder create confirm <draft-run-id> --format json
```

`confirm` 必须复用草稿中的 `message_id`、`task_id` 和三要素，不能再次 analyze。拿到确认后严禁重新执行 `create` 或 `create --auto-accept`；confirm 失败时也不得 fallback 新建任务。`--auto-accept` 只用于用户从一开始就明确授权跳过 review 的可信自动化。

正式构建使用 JSON 异步启动协议，不接收生成 SSE。保存 confirm 或可信自动化返回的 canonical `runId`，后续只用 `basebuilder runs inspect <run_id> --format json` 读取服务器状态。`queued/running/retrying` 继续等待，`succeeded` 才算完成；`failed/timed_out/cancelled/interrupted` 停止；`unknown` 表示状态无法确认，此时严禁再次执行 `create`。本地 run 只保存句柄，是否复用必须以服务器状态为准。

AI 方案初稿就是三要素页面。非交互自动化里，先展示拆解出的管理对象、管理流程、关键信息和背景知识，拿到确认后用 `create confirm` 恢复同一个任务。

多输入模式：

```bash
basebuilder create --input input.json --format json
basebuilder create --mode excel --file workbook.xlsx --file data.csv --format json
```

`--mode excel` 表示上传的一个或多个表格文件共同作为 source of truth；普通需求带文件时使用 `--mode text --file spec.md --file notes.md`，文件只是背景上下文。

三要素修改时也可以加入文件上下文。交互模式选择 `optimize` 后，按提示填写一个或多个文件路径；非交互 agent flow 使用带 `files` 的 optimize decision，不要把文件内容手工塞进一句 instruction。

## Resume And Artifacts

```bash
basebuilder runs list --format json
basebuilder create confirm <draft-run-id> --format json
basebuilder runs inspect <run_id> --format json
basebuilder report generate <run_id> --out ./report.json
basebuilder report render <run_id> --report ./report.json --out ./report.md
basebuilder artifacts manual <run_id> --from-report ./report.json --out ./manual.md
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
```

生成的 `base-skill` 是操作该具体 Base 的 per-Base Skill。读取或写入该 Base 记录前，先加载这个 Skill。

生成完成后不要直接 copy 或安装 Skill。先让用户打开 Base URL 检查表、字段、视图是否认可；用户认可后再执行 Lark copy；copy 完成并合并 `copy-result.json` 后，再询问是否让自己的 agent 学习这个表怎么用。只有用户确认后，才生成 per-Base Skill 并提示安装：

```bash
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
basebuilder skill install --source ./base-skill --target codex
```

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
- run 中断或仍在运行时只用 `runs inspect` 读取服务器状态；状态未知时停止新建，不要重复发起构建。
