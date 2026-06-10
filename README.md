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
basebuilder create --prompt "搭建一个客户成功续费风险跟进系统" --format ndjson
```

生产环境不需要配置 API 地址。本地联调才显式覆盖：

```bash
basebuilder --api-base http://127.0.0.1:8999 login
export BB_API_BASE=http://127.0.0.1:8999
```

本地状态默认写入 `~/.basebuilder`。生成的 manual 和 Skill 可能包含 Base URL、表结构和业务字段，不要写到共享目录。

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
basebuilder artifacts manual <run_id> --out ./manual.md
basebuilder artifacts skill <run_id> --out ./base-skill
```

`skills/basebuilder-cli` 是“使用 CLI 的 Skill”；`basebuilder artifacts skill` 生成的是“操作某个具体多维表的 Skill”。后者可能包含 Base URL、表结构和业务字段，只保存到可信目录。
