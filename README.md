# BaseBuilder CLI

BaseBuilder CLI 是 BaseBuilder 注册用户的本地命令行客户端。用户态 AI 请求必须通过 `weave-ai-api`，CLI 只负责登录、协议编排、本地 run metadata、manual 和 per-Base Skill 产物。

## 请求地址约定

- 生产默认请求地址是 `https://www.basebuilder.cn`，也就是 HTTPS 默认 443 端口。
- `basebuilder login` 的生产登录、device approval 和 token exchange 都走 `https://www.basebuilder.cn`。
- `http://127.0.0.1:8999` 只用于本地开发 smoke，需要通过 `--api-base` 或 `BB_API_BASE` 显式覆盖。
- CLI 不能配置或请求 Builder 直连地址；用户态 AI 请求只能进入 `www.basebuilder.cn` 背后的 `weave-ai-api`。

## Quick Start

### 安装

推荐用 `pipx` 从 GitHub main 安装，避免污染系统 Python：

```bash
pipx install git+https://github.com/MetaInFLow/basebuilder-cli.git
basebuilder health --format json
```

没有 `pipx` 时也可以用用户级 pip 安装：

```bash
python3 -m pip install --user git+https://github.com/MetaInFLow/basebuilder-cli.git
basebuilder health
```

升级到 GitHub main 最新版本：

```bash
pipx install --force git+https://github.com/MetaInFLow/basebuilder-cli.git
```

### 登录和创建

```bash
basebuilder login
basebuilder whoami --format json
basebuilder agent register
basebuilder create --input input.json --format ndjson
```

生产环境不需要配置 API 地址。本地联调才显式覆盖：

```bash
basebuilder --api-base http://127.0.0.1:8999 login
export BB_API_BASE=http://127.0.0.1:8999
```

本地状态默认写入 `~/.basebuilder`。生成的 manual 和 Skill 可能包含 Base URL、表结构和业务字段，不要写到共享目录。

### 多输入和 Excel/CSV 模式

结构化输入贴近 GUI 人类首屏模版，不要把这些字段提前拼成一句长 prompt：

```bash
basebuilder create --input input.json --format ndjson
```

`input.json` 示例：

```json
{
  "mode": "text",
  "我想要构建": "客户成功续费跟进系统",
  "我是": "客户成功团队负责人",
  "业务场景": "续费前 90 天识别风险并跟进",
  "痛点": ["续费风险靠人工记忆", "跟进动作分散在聊天记录"],
  "已有资料": "历史客户清单、续费记录、服务备注",
  "希望输出": ["客户健康度视图", "高风险续费跟进表"],
  "constraints": ["不处理财务收款"]
}
```

CLI 仍保留 `--prompt` 作为兼容入口；新 agent 或正式使用应优先生成上述 `input.json`。

Excel/CSV 结构优先模式：

```bash
basebuilder create --mode excel --file renewal.csv --format ndjson
basebuilder create --mode excel --file workbook.xlsx --file renewal.csv --file tickets.csv --format ndjson
```

`--mode excel` 会把一个或多个表格文件作为共同的 source of truth 写入结构化 intake envelope。普通文本需求附带文件时，用 `--mode text --file spec.md --file notes.md`，表示文件只是背景上下文。

三要素页面动态修改时也可以继续丢文件。交互模式里选择 `optimize` 后，CLI 会询问可选补充文件路径，多个路径用逗号分隔；agent 自动化调用 `CreateFlow` 时可以传 `{"action":"optimize","instruction":"...","files":["a.md","b.csv"]}`。

### 进度、Report 和产物

```bash
basebuilder create --prompt "..." --format ndjson
basebuilder runs inspect <run_id> --format json
basebuilder runs attach <run_id> --format ndjson
basebuilder report generate <run_id> --out ./report.json
basebuilder report render <run_id> --report ./report.json --out ./report.md
basebuilder artifacts manual <run_id> --from-report ./report.json --out ./manual.md
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
```

`report.json` 是 manual 和 per-Base Skill 的机器真相源。它来自 API 返回的 sanitized final artifact，不包含 token、cookie、raw prompt 或内部 Builder 诊断。

### 复制到自己的 Lark 空间

CLI 不保存 Lark 凭据，只通过本地 `larkcli` / `lark-cli` 的 profile 做用户自有空间操作。当前安全纵切不猜测深复制命令；复制完成后，把本地 `copy-result.json` 合并进 report：

```bash
basebuilder lark copy <run_id> --report ./report.json --copy-result ./copy-result.json
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
```

`copy-result.json` 示例：

```json
{
  "base": {
    "url": "https://your-lark-space/base/copied",
    "appToken": "copied_base_token"
  },
  "tableIdMap": {
    "tbl_original": "tbl_copied"
  },
  "fieldIdMap": {},
  "viewIdMap": {}
}
```

如果没有 `--copy-result`，CLI 会检查本地是否存在 `larkcli`。找不到时返回结构化 `LARKCLI_NOT_FOUND`；找得到但没有 copy result 时返回 `LARK_COPY_RESULT_REQUIRED`，让用户先通过本地 larkcli 完成交互式复制并导出 id map。

## Agent 注册

```bash
basebuilder agent register
basebuilder agent status --format json
basebuilder agent unregister
```

`agent register` 会向 `weave-ai-api` 发起 `intent=agent_register` 的 device session，并打印/打开授权、登录、注册和充值 URL。生产 URL 仍然来自 `https://www.basebuilder.cn`；本地 `127.*` 只在显式 dev override 下出现。

CLI 会在本地计算隐私安全指纹，只上传 `fingerprint_hash` 和低敏摘要，不上传 raw MAC、hostname、username、环境变量、cookie 或 secret。

## 给 Agent 使用的 Skill

仓库内置通用 Skill：`skills/basebuilder-cli/SKILL.md`。它用于让支持 Skills 的 agent 正确调用 CLI 登录、agent 注册、创建多维表、恢复 run、生成 manual 和 per-Base Skill。

安装到 Codex 本地 Skills：

```bash
mkdir -p ~/.codex/skills/basebuilder-cli
cp -R skills/basebuilder-cli/* ~/.codex/skills/basebuilder-cli/
```

安装到通用 agents skills 目录：

```bash
mkdir -p ~/.agents/skills/basebuilder-cli
cp -R skills/basebuilder-cli/* ~/.agents/skills/basebuilder-cli/
```

生成某个具体 Base 的专用 Skill：

```bash
basebuilder runs inspect <run_id> --format json
basebuilder report generate <run_id> --out ./report.json
basebuilder artifacts manual <run_id> --out ./manual.md
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
```

`skills/basebuilder-cli` 是“使用 CLI 的 Skill”；`basebuilder artifacts skill` 生成的是“操作某个具体多维表的 Skill”。后者可能包含 Base URL、表结构和业务字段，只保存到可信目录。
