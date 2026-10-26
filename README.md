# BaseBuilder CLI

BaseBuilder CLI 是 BaseBuilder 注册用户的本地命令行客户端。默认线上模式的用户态 AI 请求必须通过 `weave-ai-api`，CLI 负责登录、协议编排、本地 run metadata、manual 和 per-Base Skill 产物。当前源码另提供显式 `--local-dev` 本地开发模式，仅调用本机 BaseBuilder 整理需求和生成设计，不执行飞书建表；该能力尚未发布到 `v0.2.0` 稳定标签。

## 请求地址约定

- 生产默认请求地址是 `https://www.basebuilder.cn`，也就是 HTTPS 默认 443 端口。
- `basebuilder login` 的生产登录、device approval 和 token exchange 都走 `https://www.basebuilder.cn`。
- `http://127.0.0.1:8999` 只用于本地开发 smoke，需要通过 `--api-base` 或 `BB_API_BASE` 显式覆盖。
- 默认线上模式不能配置或请求 Builder 直连地址；用户态 AI 请求只能进入 `www.basebuilder.cn` 背后的 `weave-ai-api`。
- 本地仅设计模式是独立的开发例外，必须显式传入 `--local-dev --api-base http://127.0.0.1:<端口>`；不会读取线上登录配置或回退官网。

## 本地仅设计模式（当前源码，尚未发布）

本模式适用于本机 BaseBuilder → CLI → Praxis 联调，不改变线上默认行为。下面未标注 `--local-dev` 的登录、飞书构建和产物命令均属于线上模式；仅修改 `--api-base` 不会启用本地仅设计模式。

**本地服务不等于离线模型。** `create`、`create optimize` 和 `design draft` 可能调用收费模型，执行前须获得授权；`doctor` 只检查连接、鉴权和协议，不调用模型，也不证明真实 AI 设计质量。

### 启动本机 BaseBuilder

使用已安装 BaseBuilder 依赖的 Python。以下为 Bash 示例（Windows 可用 Git Bash），将路径改成自己的绝对路径；`BB_PYTHON`、`CLI_PYTHON` 分别指向两仓已有虚拟环境的 Python，Windows 通常是 `.venv/Scripts/python.exe`，Unix 通常是 `.venv/bin/python`。

在服务端终端执行：

```bash
export BB_PYTHON="/absolute/path/BaseBuilder/.venv/Scripts/python.exe"
export PYTHONPATH="/absolute/path/BaseBuilder/src"
export BB_LOCAL_ORIGIN="http://127.0.0.1:8999"
export BB_LOCAL_STATE_DIR="/absolute/path/private-local/builder-state"
export BB_LOCAL_TOKEN_FILE="/absolute/path/private-local/local-token"
export BB_LOCAL_MODEL_CONFIG="/absolute/path/private-local/model.yaml"

# 仅首次执行，不覆盖已有 token，也不打印凭据。
"$BB_PYTHON" -X utf8 -m base_builder.local.app --init-token
"$BB_PYTHON" -X utf8 -m base_builder.local.app
```

`model.yaml` 使用 BaseBuilder 的 `selection` / `providers` YAML 格式，配置 provider、model_name 和相应模型认证信息。只有 BaseBuilder 服务端需要模型配置，CLI 不需要模型凭据。专用 token、模型配置、请求数据库和草稿目录均应放在可信私有目录，不入 Git、不共享；Windows 还应限制目录 ACL。不要复用线上登录 token。

服务只监听数字回环地址。CLI 只接受 `http://127.0.0.1:<端口>`，拒绝 `localhost`、其他主机、路径、查询串和 HTTP 重定向，不使用系统 HTTP 代理；服务拒绝浏览器 Origin，不提供 CORS。

### 检查连接、生成和优化三要素

在另一个终端显式使用当前 CLI 源码，不使用已发布的 `v0.2.0`：

```bash
export CLI_PYTHON="/absolute/path/BaseBuilder-CLI/.venv/Scripts/python.exe"
export PYTHONPATH="/absolute/path/BaseBuilder-CLI/src"
export BB_LOCAL_TOKEN_FILE="/absolute/path/private-local/local-token"
export BB_LOCAL_HOME="/absolute/path/private-local/cli-state"

"$CLI_PYTHON" -X utf8 -m basebuilder_cli --local-dev --api-base http://127.0.0.1:8999 doctor --format json

# 以下命令会调用模型，仅在获授权后执行。
"$CLI_PYTHON" -X utf8 -m basebuilder_cli --local-dev --api-base http://127.0.0.1:8999 create \
  --prompt "客户跟进系统" --request-id analyze-001 --format json
"$CLI_PYTHON" -X utf8 -m basebuilder_cli --local-dev --api-base http://127.0.0.1:8999 create optimize local-analyze-001 \
  --instruction "增加客户阶段，保留原字段" --request-id optimize-001 --format json
```

`BB_LOCAL_HOME` 必须是绝对路径，与线上 `BB_HOME` 分离。两个进程争用同一本地目录时，后启动的命令会拒绝执行，应等原命令结束再查询。示例请求 ID 只用于演示：每个新需求或新优化使用新 ID，恢复同一请求则保留原 ID 和原输入。

### 审核三要素，再生成详细设计

先展示并审核最新三要素。准备 `context.json`，只能包含下面四个键，其中 `runId` 和 `elements` 必须与原草稿完全一致，不能用示例文本代替实际回执：

```json
{
  "runId": "local-analyze-001",
  "elements": {
    "manage_what": "使用最新回执原值",
    "workflow": "使用最新回执原值",
    "fields": "使用最新回执原值"
  },
  "intake": {},
  "sourceSignature": "demo-confirmed-requirement-v1"
}
```

如果回执包含 `backgroundKnowledge`，也必须原样保留在 `elements` 中。`intake` 保存已确认需求背景，`sourceSignature` 绑定该需求版本。Praxis 接入时由服务端生成并核对上下文，不应手工替换。

```bash
"$CLI_PYTHON" -X utf8 -m basebuilder_cli --local-dev --api-base http://127.0.0.1:8999 design draft local-analyze-001 \
  --request-id design-001 --input /absolute/path/context.json --format json
"$CLI_PYTHON" -X utf8 -m basebuilder_cli --local-dev --api-base http://127.0.0.1:8999 design inspect local-analyze-001 \
  --request-id design-001 --format json
"$CLI_PYTHON" -X utf8 -m basebuilder_cli --local-dev --api-base http://127.0.0.1:8999 runs inspect local-analyze-001 --format json
```

`design draft` 返回原请求状态；`queued` / `running` 时用 `design inspect` 查询，成功后返回 `basebuilder.system-design/v1` 的 `design`。CLI 不创建原生业务表，详细设计还需在 Praxis 中审核并再次确认发布。不要执行线上的 `create confirm`：local 会拒绝该命令，也不支持 login、agent、报告、飞书操作、文件附件或 Excel 模式。

### 请求恢复与限制

- 请求 ID 绑定操作和输入；恢复必须保留原 ID、原输入与原状态目录，不能用同 ID 提交不同内容。
- 服务或网络异常时不要换 ID 重做。已提交的设计用 `design inspect`；分析或优化可在核对原请求后，以原 ID 和完全相同参数恢复。`runs inspect` 优先查询设计，否则查询最初分析，不用于查询待完成的优化。
- `failed` / `interrupted` 需要人工核对，不自动重调模型。重启后遗留 `running` 标记为 `interrupted`，未执行的 `queued` 可以继续；不承诺模型调用与落盘之间崩溃时的 exactly-once。
- 草稿绑定 origin 和持久 serviceId。更换端口、服务状态目录或服务身份后，不能拿旧草稿继续执行；重启原服务须保留原目录和配置。
- 查询未找到不能证明模型未执行，应核对服务和本地状态，不擅自新建请求。目前没有自动修复所有“本地已保存、服务尚未入队”的断点。

### CLI 完整离线回归

先按上文设置 `CLI_PYTHON` 和 CLI 的 `PYTHONPATH`，再隔离用户目录运行。测试使用替身或本机 HTTP，不调用真实模型；`-X utf8` 避免 Windows 默认编码影响中文夹具。

```bash
TEST_HOME="$("$CLI_PYTHON" -X utf8 -c 'import tempfile; print(tempfile.mkdtemp(prefix="basebuilder-cli-tests-"))')"
HOME="$TEST_HOME" USERPROFILE="$TEST_HOME" BB_HOME="$TEST_HOME/online" BB_LOCAL_HOME="$TEST_HOME/local" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
  "$CLI_PYTHON" -X utf8 -m unittest discover -s /absolute/path/BaseBuilder-CLI/tests -v
```

临时测试目录可能包含合成草稿和 Skill，核对后自行清理；不要对真实用户目录运行未隔离测试。

## Quick Start

### 安装

推荐用 `pipx` 安装稳定版 `v0.2.0`，避免污染系统 Python：

```bash
pipx install "git+https://github.com/MetaInFLow/basebuilder-cli.git@v0.2.0"
basebuilder --version
basebuilder doctor
basebuilder skill install --target codex
```

没有 `pipx` 时也可以用用户级 pip 安装：

```bash
python3 -m pip install --user "git+https://github.com/MetaInFLow/basebuilder-cli.git@v0.2.0"
basebuilder --version
basebuilder doctor
basebuilder skill install --target codex
```

重新安装当前稳定版：

```bash
pipx install --force "git+https://github.com/MetaInFLow/basebuilder-cli.git@v0.2.0"
```

开发者需要跟踪 GitHub main 时使用：

```bash
pipx install --force "git+https://github.com/MetaInFLow/basebuilder-cli.git@main"
```

### 登录和创建

```bash
basebuilder login
basebuilder doctor
basebuilder whoami --format json
basebuilder create --input input.json --format json
```

`basebuilder login` 成功后会自动为本机 agent 注册/轮换 agent token，不需要用户再打开一个 agent 注册确认页。只有 `doctor` 提示 token 缺失、吊销或需要重新注册时，才单独运行 `basebuilder agent register`。

生产环境不需要配置 API 地址。本地联调才显式覆盖：

```bash
basebuilder --api-base http://127.0.0.1:8999 login
export BB_API_BASE=http://127.0.0.1:8999
```

本地状态默认写入 `~/.basebuilder`。生成的 manual 和 Skill 可能包含 Base URL、表结构和业务字段，不要写到共享目录。

### Doctor 诊断

遇到“不能用、登录失败、连不上、没次数、任务还在跑、run 断了”等问题，先运行：

```bash
basebuilder doctor
basebuilder doctor --format json
```

`doctor` 会检查：

- 当前 API 地址是否能连通，生产默认是 `https://www.basebuilder.cn`。
- 本地是否已经登录，token 是否过期/吊销。
- 当前账号是否还有可识别的构建次数；次数为 0 时会提示去 Web 充值。
- 本地最近 run 是否仍在运行，并提示 `basebuilder runs inspect <run_id> --format json`。
- 本地是否安装 `larkcli` / `lark-cli`，用于复制到自己的 Lark 空间。

`doctor` 本身不会发起构建，也不会直连 Builder。它只读取本地状态，并通过 `weave-ai-api` 做健康、登录和 run snapshot 检查。

### 多输入和 Excel/CSV 模式

结构化输入贴近 GUI 人类首屏模版，不要把这些字段提前拼成一句长 prompt：

```bash
basebuilder create --input input.json --format json
```

`input.json` 示例：

```json
{
  "mode": "text",
  "我想要构建": "客户成功续费跟进系统",
  "我是": "客户成功团队负责人",
  "主要使用者": "客户成功经理、销售主管",
  "业务背景": "续费前 90 天识别风险并跟进",
  "核心痛点": ["续费风险靠人工记忆", "跟进动作分散在聊天记录"],
  "已有资料": "历史客户清单、续费记录、服务备注",
  "希望输出": ["客户健康度视图", "高风险续费跟进表"],
  "constraints": ["不处理财务收款"],
  "背景知识": "企业客户续费通常需要提前触达使用率下降和关键人变更。"
}
```

CLI 仍保留 `--prompt` 作为兼容入口；新 agent 或正式使用应优先生成上述 `input.json`。

### AI 方案初稿确认

CLI 里的“AI 方案初稿”就是 Web 里的三要素页面。分析完成后会一次性输出：

- 管理对象
- 管理流程
- 关键信息
- 背景知识

默认不会直接开始搭建。交互模式可以直接输入 `accept`；非交互模式返回 `confirmationRequired=true` 和本地草稿 `runId` 后，必须先向用户展示三要素，确认后恢复该草稿：

```bash
basebuilder create confirm <draft-run-id> --format json
```

`confirm` 会复用草稿中的 `message_id`、`task_id` 和三要素，不会再次执行 analyze。不要在用户确认后重新运行 `create` 或 `create --auto-accept`，否则会破坏同一任务的会话 lineage；CLI 也会用 `DRAFT_CONFIRMATION_REQUIRED` 阻止相同需求绕过待确认草稿。`--auto-accept` 只用于用户从一开始就明确授权跳过 review 的可信自动化。需要修改时可以选择 `edit`，或用 `optimize` 加一句调整要求；`optimize` 可以继续附加多个文件作为上下文。

当前开发候选增加了非交互方案优化命令（尚未发布到上述 `v0.2.0` 稳定标签）：

```bash
basebuilder create optimize <draft-run-id> --instruction "增加回款跟进，保留客户字段" --format json
```

此命令只更新原待确认草稿，保留任务上下文，不会开始构建。优化后需要重新审核并执行 `create confirm`。如果优化结果无法确认，旧草稿保留，但应先核对原任务，不自动重试或确认构建。

Excel/CSV 结构优先模式：

```bash
basebuilder create --mode excel --file renewal.csv --format json
basebuilder create --mode excel --file workbook.xlsx --file renewal.csv --file tickets.csv --format json
```

`--mode excel` 会把一个或多个表格文件作为共同的 source of truth 写入结构化 intake envelope。普通文本需求附带文件时，用 `--mode text --file spec.md --file notes.md`，表示文件只是背景上下文。

三要素页面动态修改时也可以继续丢文件。交互模式里选择 `optimize` 后，CLI 会询问可选补充文件路径，多个路径用逗号分隔；agent 自动化调用 `CreateFlow` 时可以传 `{"action":"optimize","instruction":"...","files":["a.md","b.csv"]}`。

### 进度、Report 和产物

```bash
basebuilder create --prompt "..." --format json
basebuilder create confirm <draft-run-id> --format json
basebuilder runs inspect <run_id> --format json
basebuilder report generate <run_id> --out ./report.json
basebuilder report render <run_id> --report ./report.json --out ./report.md
basebuilder artifacts manual <run_id> --from-report ./report.json --out ./manual.md
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
```

`create` 通过 JSON 异步协议启动任务，成功后立即返回，不建立生成 SSE。之后只用 `runs inspect` 读取服务器状态：`queued/running/retrying` 继续等待，`succeeded` 表示完成，`failed/timed_out/cancelled/interrupted` 表示终止，`unknown` 表示当前无法确认。CLI 本地文件只是 run 句柄缓存；重复创建前必须先刷新服务器状态，无法确认时停止新建，避免重复扣费。

`report.json` 是 manual 和 per-Base Skill 的机器真相源。它来自 API 返回的 sanitized final artifact，不包含 token、cookie、raw prompt 或内部 Builder 诊断。

### 复制到自己的 Lark 空间

CLI 不保存 Lark 凭据，只通过本地 `larkcli` / `lark-cli` 的 profile 做用户自有空间操作。当前安全纵切不猜测深复制命令；复制完成后，把本地 `copy-result.json` 合并进 report：

```bash
basebuilder lark copy <run_id> --report ./report.json --copy-result ./copy-result.json
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
basebuilder skill install --source ./base-skill --target codex
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

有有效 token 时，`agent register` 会直接调用受保护 API 完成本机 agent 注册/轮换，不再弹出浏览器确认。没有 token 时，它才会向 `weave-ai-api` 发起 `intent=agent_register` 的 device session，并打印/打开授权、登录、注册和充值 URL。生产 URL 仍然来自 `https://www.basebuilder.cn`；本地 `127.*` 只在显式 dev override 下出现。

CLI 会在本地计算隐私安全指纹，只上传 `fingerprint_hash` 和低敏摘要，不上传 raw MAC、hostname、username、环境变量、cookie 或 secret。

## 给 Agent 使用的 Skill

仓库内置通用 Skill：`skills/basebuilder-cli/SKILL.md`。它用于让支持 Skills 的 agent 正确调用 CLI 登录、agent 注册、创建多维表、恢复 run、生成 manual 和 per-Base Skill。

安装到 Codex 本地 Skills：

```bash
basebuilder skill install --target codex
```

安装到通用 agents skills 目录：

```bash
basebuilder skill install --target agents
```

生成某个具体 Base 的专用 Skill：

```bash
basebuilder runs inspect <run_id> --format json
basebuilder report generate <run_id> --out ./report.json
basebuilder artifacts manual <run_id> --out ./manual.md
basebuilder artifacts skill <run_id> --from-report ./report.json --out ./base-skill
basebuilder skill install --source ./base-skill --target codex
```

`skills/basebuilder-cli` 是“使用 CLI 的 Skill”；`basebuilder artifacts skill` 生成的是“操作某个具体多维表的 Skill”。后者可能包含 Base URL、表结构和业务字段，只保存到可信目录。
