# BaseBuilder CLI

BaseBuilder CLI 是 BaseBuilder 注册用户的本地命令行客户端。用户态 AI 请求必须通过 `weave-ai-api`，CLI 只负责登录、协议编排、本地 run metadata、manual 和 per-Base Skill 产物。

## 请求地址约定

- 生产默认请求地址是 `https://www.basebuilder.cn`，也就是 HTTPS 默认 443 端口。
- `basebuilder login` 的生产登录、device approval 和 token exchange 都走 `https://www.basebuilder.cn`。
- `http://127.0.0.1:8999` 只用于本地开发 smoke，需要通过 `--api-base` 或 `BB_API_BASE` 显式覆盖。
- CLI 不能配置或请求 Builder 直连地址；用户态 AI 请求只能进入 `www.basebuilder.cn` 背后的 `weave-ai-api`。

## Quick Start

```bash
python -m basebuilder_cli health
python -m basebuilder_cli login
python -m basebuilder_cli whoami
python -m basebuilder_cli agent register
python -m basebuilder_cli create --format ndjson
```

生产环境不需要配置 API 地址。本地联调才显式覆盖：

```bash
python -m basebuilder_cli --api-base http://127.0.0.1:8999 login
export BB_API_BASE=http://127.0.0.1:8999
```

本地状态默认写入 `~/.basebuilder`。生成的 manual 和 Skill 可能包含 Base URL、表结构和业务字段，不要写到共享目录。

## Agent 注册

```bash
python -m basebuilder_cli agent register
python -m basebuilder_cli agent status --format json
python -m basebuilder_cli agent unregister
```

`agent register` 会向 `weave-ai-api` 发起 `intent=agent_register` 的 device session，并打印/打开授权、登录、注册和充值 URL。生产 URL 仍然来自 `https://www.basebuilder.cn`；本地 `127.*` 只在显式 dev override 下出现。

CLI 会在本地计算隐私安全指纹，只上传 `fingerprint_hash` 和低敏摘要，不上传 raw MAC、hostname、username、环境变量、cookie 或 secret。
