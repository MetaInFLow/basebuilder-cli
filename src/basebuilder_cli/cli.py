from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import webbrowser
from pathlib import Path
from typing import Any

from . import __version__
from .artifacts import write_manual, write_skill
from .client import ApiError, BaseBuilderApiClient, poll_for_token
from .config import CliConfig, DEFAULT_API_BASE, clear_token, load_config, save_config, state_dir
from .create_flow import CreateFlow, CreateResult, ThreeElements, extract_message_id, extract_task_id, normalize_elements
from .doctor import DoctorOptions, render_doctor_human, run_doctor
from .fingerprint import build_fingerprint
from .intake import build_intake_prompt, build_refine_instruction
from .protocol import dumps, error_envelope, ok_envelope
from .report import build_report, materialize_report_artifact, merge_copy_result, read_report, render_report_markdown, require_larkcli, write_report
from .runs import list_runs, load_run, new_run_id, promote_run, resolve_run_id, save_run


COMMANDS = [
    "health",
    "doctor",
    "login",
    "logout",
    "whoami",
    "create",
    "create confirm",
    "runs list",
    "runs inspect",
    "runs attach",
    "artifacts manual",
    "artifacts skill",
    "report generate",
    "report render",
    "lark copy",
    "agent register",
    "agent status",
    "agent unregister",
    "skill install",
    "ext describe",
    "ext call",
]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ApiError as exc:
        print(dumps(error_envelope(getattr(args, "operation", "cli"), exc.code, str(exc), retryable=exc.retryable)))
        return 1
    except Exception as exc:
        print(dumps(error_envelope(getattr(args, "operation", "cli"), "CLI_ERROR", str(exc), retryable=False)))
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="basebuilder",
        description=(
            "BaseBuilder CLI. Production login and API requests default to "
            f"{DEFAULT_API_BASE} over HTTPS. Local 127.* addresses are for explicit dev smoke only."
        ),
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help=(
            f"API base URL. Production default: {DEFAULT_API_BASE} "
            "(HTTPS port 443). Use http://127.0.0.1:8999 only for explicit local dev smoke."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser("health")
    health.add_argument("--format", choices=["human", "json"], default="human")
    health.set_defaults(func=cmd_health, operation="health")

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--format", choices=["human", "json"], default="human")
    doctor.add_argument("--max-runs", type=int, default=5)
    doctor.set_defaults(func=cmd_doctor, operation="doctor")

    login = sub.add_parser("login")
    login.add_argument("--no-open", action="store_true")
    login.add_argument("--device-name", default=None)
    login.set_defaults(func=cmd_login, operation="auth.login")

    logout = sub.add_parser("logout")
    logout.set_defaults(func=cmd_logout, operation="auth.logout")

    whoami = sub.add_parser("whoami")
    whoami.add_argument("--format", choices=["human", "json"], default="human")
    whoami.set_defaults(func=cmd_whoami, operation="me")

    create = sub.add_parser("create")
    create.add_argument("create_action", nargs="?", choices=["confirm"])
    create.add_argument("draft_run_id", nargs="?")
    create.add_argument("--prompt", default="")
    create.add_argument("--input", default="", help="JSON structured intake file.")
    create.add_argument("--mode", choices=["text", "excel"], default="text")
    create.add_argument("--file", action="append", default=[])
    create.add_argument("--format", choices=["human", "json", "ndjson"], default="human")
    create.add_argument("--auto-accept", action="store_true")
    create.add_argument(
        "--wait",
        action="store_true",
        help="Keep polling until the build finishes. By default create returns after the task starts.",
    )
    create.set_defaults(func=cmd_create, operation="builds.create")

    runs = sub.add_parser("runs")
    runs_sub = runs.add_subparsers(dest="runs_command", required=True)
    runs_list = runs_sub.add_parser("list")
    runs_list.add_argument("--format", choices=["human", "json"], default="human")
    runs_list.set_defaults(func=cmd_runs_list, operation="runs.list")
    runs_inspect = runs_sub.add_parser("inspect")
    runs_inspect.add_argument("run_id")
    runs_inspect.add_argument("--format", choices=["human", "json"], default="human")
    runs_inspect.set_defaults(func=cmd_runs_inspect, operation="runs.inspect")
    runs_attach = runs_sub.add_parser("attach")
    runs_attach.add_argument("run_id")
    runs_attach.add_argument("--format", choices=["human", "ndjson"], default="human")
    runs_attach.set_defaults(func=cmd_runs_attach, operation="runs.attach")

    artifacts = sub.add_parser("artifacts")
    artifacts_sub = artifacts.add_subparsers(dest="artifact_command", required=True)
    manual = artifacts_sub.add_parser("manual")
    manual.add_argument("run_id")
    manual.add_argument("--from-report", default="")
    manual.add_argument("--out", required=True)
    manual.set_defaults(func=cmd_artifact_manual, operation="artifacts.manual")
    skill = artifacts_sub.add_parser("skill")
    skill.add_argument("run_id")
    skill.add_argument("--from-report", default="")
    skill.add_argument("--out", required=True)
    skill.set_defaults(func=cmd_artifact_skill, operation="artifacts.skill")

    report = sub.add_parser("report")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    report_generate = report_sub.add_parser("generate")
    report_generate.add_argument("run_id")
    report_generate.add_argument("--out", required=True)
    report_generate.set_defaults(func=cmd_report_generate, operation="report.generate")
    report_render = report_sub.add_parser("render")
    report_render.add_argument("run_id")
    report_render.add_argument("--report", default="")
    report_render.add_argument("--out", required=True)
    report_render.set_defaults(func=cmd_report_render, operation="report.render")

    lark = sub.add_parser("lark")
    lark_sub = lark.add_subparsers(dest="lark_command", required=True)
    lark_copy = lark_sub.add_parser("copy")
    lark_copy.add_argument("run_id")
    lark_copy.add_argument("--report", required=True)
    lark_copy.add_argument("--copy-result", default="")
    lark_copy.add_argument("--profile", default="")
    lark_copy.add_argument("--target-folder", default="")
    lark_copy.set_defaults(func=cmd_lark_copy, operation="lark.copy")

    agent = sub.add_parser("agent")
    agent_sub = agent.add_subparsers(dest="agent_command", required=True)
    agent_register = agent_sub.add_parser("register")
    agent_register.add_argument("--no-open", action="store_true")
    agent_register.add_argument("--device-name", default=None)
    agent_register.add_argument("--format", choices=["human", "json"], default="human")
    agent_register.set_defaults(func=cmd_agent_register, operation="agents.register")
    agent_status = agent_sub.add_parser("status")
    agent_status.add_argument("--format", choices=["human", "json"], default="human")
    agent_status.set_defaults(func=cmd_agent_status, operation="agents.status")
    agent_unregister = agent_sub.add_parser("unregister")
    agent_unregister.set_defaults(func=cmd_agent_unregister, operation="agents.unregister")

    skill_cmd = sub.add_parser("skill")
    skill_sub = skill_cmd.add_subparsers(dest="skill_command", required=True)
    skill_install = skill_sub.add_parser("install")
    skill_install.add_argument("--target", choices=["codex", "agents"], default="codex")
    skill_install.add_argument("--path", default="", help="Install destination. Defaults to the selected target skills directory.")
    skill_install.add_argument("--source", default="", help="Source skill directory. Defaults to this repo's generic basebuilder-cli skill.")
    skill_install.set_defaults(func=cmd_skill_install, operation="skill.install")

    ext = sub.add_parser("ext")
    ext_sub = ext.add_subparsers(dest="ext_command", required=True)
    describe = ext_sub.add_parser("describe")
    describe.add_argument("--format", choices=["json"], default="json")
    describe.set_defaults(func=cmd_ext_describe, operation="ext.describe")
    call = ext_sub.add_parser("call")
    call.add_argument("operation_name")
    call.add_argument("--input-json", default="{}")
    call.set_defaults(func=cmd_ext_call, operation="ext.call")

    return parser


def cmd_health(args: argparse.Namespace) -> int:
    data = {
        "name": "basebuilder-cli",
        "version": __version__,
        "api_base": make_config(args).api_base,
        "commands": COMMANDS,
    }
    return emit(args.format, "health", data, human=f"basebuilder-cli {__version__} api={data['api_base']}")


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(
        config=make_config(args),
        api_factory=BaseBuilderApiClient,
        options=DoctorOptions(max_runs=max(0, int(args.max_runs or 0))),
    )
    if args.format == "json":
        print(dumps(ok_envelope("doctor", report)))
    else:
        print(render_doctor_human(report))
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    cfg = make_config(args)
    client = BaseBuilderApiClient(cfg.api_base)
    session = client.device_start(args.device_name or default_device_name())
    if not args.no_open:
        webbrowser.open(session["verification_url"])
    print(f"当前 API: {cfg.api_base}")
    if cfg.api_base == DEFAULT_API_BASE:
        print("生产登录请求走 https://www.basebuilder.cn（HTTPS 443）。")
    else:
        print("当前使用非生产 API，仅用于显式本地开发测试。")
    print(f"打开浏览器完成登录: {session['verification_url']}")
    print(f"确认码: {session['user_code']}")
    token = poll_for_token(client, session["device_code"], int(session["expires_at"]), int(session.get("poll_interval") or 5))
    human_token = str(token["access_token"])
    agent = register_agent_with_token(cfg.api_base, human_token, args.device_name or default_device_name())
    agent_token = str(agent.get("access_token") or human_token)
    save_config(CliConfig(api_base=cfg.api_base, token=agent_token))
    print("登录成功")
    print("Agent 自动注册成功，无需第二次授权确认。")
    if agent.get("agent_identity_id"):
        print(f"agent_id: {agent.get('agent_identity_id')}")
    return 0


def cmd_agent_register(args: argparse.Namespace) -> int:
    cfg = make_config(args)
    if cfg.token:
        data = register_agent_with_token(cfg.api_base, cfg.token, args.device_name or default_device_name())
        if data.get("access_token"):
            save_config(CliConfig(api_base=cfg.api_base, token=str(data["access_token"])))
        data["mode"] = "authenticated"
        if args.format == "json":
            print(dumps(ok_envelope("agents.register", data)))
        else:
            print("Agent 已自动注册，无需再次打开浏览器确认。")
            print(f"agent_id: {data.get('agent_identity_id') or ''}")
        return 0

    client = BaseBuilderApiClient(cfg.api_base)
    fingerprint = build_fingerprint(state_dir())
    session = client.device_start(
        args.device_name or default_device_name(),
        intent="agent_register",
        client_kind="agent",
        fingerprint_hash=str(fingerprint["fingerprint_hash"]),
        fingerprint_signals=dict(fingerprint["fingerprint_signals"]),
    )
    data = agent_registration_payload(session, fingerprint)
    verification_url = str(data.get("verificationUrl") or "")

    if args.format == "json":
        print(dumps(ok_envelope("agents.register", data)))
        return 0

    if verification_url and not args.no_open:
        webbrowser.open(verification_url)
    print(f"当前 API: {cfg.api_base}")
    if cfg.api_base == DEFAULT_API_BASE:
        print("Agent 注册请求走 https://www.basebuilder.cn（HTTPS 443）。")
    else:
        print("当前使用非生产 API，仅用于显式本地开发测试。")
    print(f"授权页面: {verification_url}")
    print(f"登录页面: {data.get('loginUrl') or ''}")
    print(f"注册页面: {data.get('registerUrl') or ''}")
    print(f"充值页面: {data.get('rechargeUrl') or ''}")
    print(f"确认码: {data.get('userCode') or ''}")

    token = poll_for_token(client, str(session["device_code"]), int(session["expires_at"]), int(session.get("poll_interval") or 5))
    save_config(CliConfig(api_base=cfg.api_base, token=str(token["access_token"])))
    print("Agent 注册并登录成功")
    return 0


def cmd_agent_status(args: argparse.Namespace) -> int:
    cfg = make_config(args)
    data = BaseBuilderApiClient(cfg.api_base, cfg.token).agent_current()
    label = data.get("device_name") or data.get("clientKind") or data.get("client_kind") or "agent"
    return emit(args.format, "agents.status", data, human=f"BaseBuilder CLI Agent: {label}")


def cmd_agent_unregister(args: argparse.Namespace) -> int:
    cfg = make_config(args)
    data = BaseBuilderApiClient(cfg.api_base, cfg.token).agent_unregister()
    clear_token()
    print(dumps(ok_envelope("agents.unregister", data or {"revoked": True})))
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    cfg = make_config(args)
    if cfg.token:
        BaseBuilderApiClient(cfg.api_base, cfg.token).logout()
    clear_token()
    print(dumps(ok_envelope("auth.logout", {"revoked": True})))
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    cfg = make_config(args)
    data = BaseBuilderApiClient(cfg.api_base, cfg.token).me()
    user = data.get("user") or {}
    return emit(args.format, "me", data, human=f"{user.get('nickname') or user.get('email') or user.get('phone') or user.get('id')}")


def cmd_create(args: argparse.Namespace) -> int:
    if args.create_action == "confirm":
        return cmd_create_confirm(args)

    cfg = make_config(args)
    prompt_text = args.prompt
    structured_input: dict[str, Any] | None = None
    if not prompt_text and not args.input and not args.file:
        if sys.stdin.isatty():
            structured_input = read_template_input()
        else:
            prompt_text = read_prompt()
    prompt = build_intake_prompt(
        prompt=prompt_text,
        mode=args.mode,
        input_path=args.input,
        files=args.file,
        structured_input=structured_input,
    )
    client = BaseBuilderApiClient(cfg.api_base, cfg.token)
    active_run = find_matching_active_run(client, prompt)
    if active_run:
        return emit_reused_active_run(args.format, active_run)

    emitted_stdout = False
    if not args.auto_accept and sys.stdin.isatty():
        result, emitted_stdout = run_interactive_create(client, prompt, args.format)
    else:
        decisions: list[Any] = ["accept"] if args.auto_accept else ["show"]
        flow = CreateFlow(client)
        result = flow.run(prompt, decisions)
    run_id = str(result.run.get("runId") or result.run.get("run_id") or new_run_id())
    latest_progress: dict[str, Any] = {}
    save_run(run_id, {
        "run_id": run_id,
        "prompt": prompt,
        "intake": {
            "mode": args.mode,
            "input": args.input,
            "files": args.file,
            "template": structured_input or {},
        },
        "elements": result.elements.to_dict(),
        "api_run": result.run,
        "status": result.status,
        "message_id": result.message_id,
        "task_id": result.task_id,
    })

    if emitted_stdout:
        pass
    elif args.format == "ndjson":
        print(dumps(ok_envelope("builds.analyze", result.elements.to_dict(), {"runId": run_id, "messageId": result.message_id, "taskId": result.task_id})))
        print(dumps(ok_envelope("builds.create", create_result_payload(result, run_id), {"runId": run_id, "messageId": result.message_id, "taskId": result.task_id})))
    elif args.format == "json":
        print(dumps(ok_envelope("builds.create", create_result_payload(result, run_id))))
    else:
        print("AI 方案初稿 / 三要素:")
        print("管理对象: " + result.elements.manage_what)
        print("流程: " + result.elements.workflow)
        print("字段: " + result.elements.fields)
        if result.elements.background_knowledge:
            print("背景知识: " + result.elements.background_knowledge)
        print("状态: " + result.status)
        print("run_id: " + run_id)

    if result.status == "building" and args.wait and args.format in {"human", "ndjson"}:
        for event in client.attach_progress(run_id):
            latest_progress = compact_progress_data(event.data)
            if args.format == "ndjson":
                print(dumps(ok_envelope("runs.attach.progress", latest_progress, {"event": event.type, "runId": run_id})))
            else:
                print_progress_event(event.type, latest_progress)

    if latest_progress:
        save_run(run_id, {
            "latest_progress": latest_progress,
            "status": str(latest_progress.get("status") or latest_progress.get("state") or result.status),
        })
        if args.format == "human" and result.status == "building":
            print_post_build_guidance(run_id, latest_progress)
    elif result.status == "building" and args.format == "human":
        print("任务已在后台运行，CLI 不会持续轮询。")
        print(f"查看一次状态: basebuilder runs inspect {run_id} --format json")
    return 0


def cmd_create_confirm(args: argparse.Namespace) -> int:
    draft_run_id = str(args.draft_run_id or "").strip()
    if not draft_run_id:
        raise ApiError(
            "DRAFT_RUN_ID_REQUIRED",
            "请提供待确认的草稿 run id：basebuilder create confirm <draft-run-id>。",
            retryable=False,
        )

    try:
        row = load_run(draft_run_id)
    except FileNotFoundError as exc:
        raise ApiError("DRAFT_RUN_NOT_FOUND", f"未找到本地草稿 run：{draft_run_id}", retryable=False) from exc

    try:
        message_id = int(row.get("message_id") or 0)
    except (TypeError, ValueError):
        message_id = 0
    task_id = str(row.get("task_id") or "").strip()
    if message_id <= 0 or not task_id:
        raise ApiError(
            "DRAFT_TASK_CONTEXT_MISSING",
            "草稿缺少 message_id 或 task_id，已停止确认；不会创建新任务。",
            retryable=False,
        )

    elements = normalize_elements(row.get("elements") if isinstance(row.get("elements"), dict) else {})
    if any(not str(getattr(elements, key) or "").strip() for key in ("manage_what", "workflow", "fields")):
        raise ApiError(
            "DRAFT_ELEMENTS_INVALID",
            "草稿三要素不完整，已停止确认；不会创建新任务。",
            retryable=False,
        )

    cfg = make_config(args)
    client = BaseBuilderApiClient(cfg.api_base, cfg.token)
    run = client.start_build(elements, message_id=message_id, task_id=task_id)
    canonical_run_id = str(run.get("runId") or run.get("run_id") or f"message_{message_id}").strip()
    if not canonical_run_id:
        raise ApiError("BUILD_RUN_ID_MISSING", "服务端未返回 run id，草稿仍保留，请稍后重试确认。", retryable=True)

    status = str(run.get("status") or "building").strip() or "building"
    source_draft_run_id = str(row.get("draft_run_id") or draft_run_id).strip() or draft_run_id
    promote_run(source_draft_run_id, canonical_run_id, {
        **row,
        "api_run": run,
        "status": status,
        "message_id": message_id,
        "task_id": extract_task_id(run) or task_id,
    })

    result = CreateResult(
        status=status,
        elements=elements,
        run=run,
        message_id=message_id,
        task_id=extract_task_id(run) or task_id,
    )
    payload = create_result_payload(result, canonical_run_id)
    payload["confirmedFromDraftRunId"] = source_draft_run_id

    if args.format in {"json", "ndjson"}:
        print(dumps(ok_envelope("builds.confirm", payload, {
            "runId": canonical_run_id,
            "messageId": message_id,
            "taskId": result.task_id,
            "draftRunId": source_draft_run_id,
        })))
    else:
        print("方案已确认，已在原任务上开始搭建。")
        print("run_id: " + canonical_run_id)

    latest_progress: dict[str, Any] = {}
    if args.wait and args.format in {"human", "ndjson"}:
        for event in client.attach_progress(canonical_run_id):
            latest_progress = compact_progress_data(event.data)
            if args.format == "ndjson":
                print(dumps(ok_envelope("runs.attach.progress", latest_progress, {
                    "event": event.type,
                    "runId": canonical_run_id,
                })))
            else:
                print_progress_event(event.type, latest_progress)

    if latest_progress:
        save_run(canonical_run_id, {
            "latest_progress": latest_progress,
            "status": str(latest_progress.get("status") or latest_progress.get("state") or status),
        })
        if args.format == "human":
            print_post_build_guidance(canonical_run_id, latest_progress)
    elif args.format == "human":
        print("任务已在后台运行，CLI 不会持续轮询。")
        print(f"查看一次状态: basebuilder runs inspect {canonical_run_id} --format json")
    return 0


def cmd_runs_list(args: argparse.Namespace) -> int:
    rows = list_runs()
    if args.format == "json":
        print(dumps(ok_envelope("runs.list", {"items": rows})))
    else:
        for row in rows:
            print(f"{row.get('run_id')} {row.get('status')}")
    return 0


def cmd_runs_inspect(args: argparse.Namespace) -> int:
    row = load_run(args.run_id)
    canonical_run_id = resolve_run_id(args.run_id)
    cfg = make_config(args)
    if cfg.token:
        snapshot = compact_progress_data(BaseBuilderApiClient(cfg.api_base, cfg.token).run_snapshot(canonical_run_id))
        row["snapshot"] = snapshot
        row["status"] = str(snapshot.get("status") or snapshot.get("state") or row.get("status") or "")
        save_run(canonical_run_id, {"snapshot": snapshot, "status": row["status"]})
    return emit(args.format, "runs.inspect", row, human=json.dumps(row, ensure_ascii=False, indent=2))


def cmd_runs_attach(args: argparse.Namespace) -> int:
    cfg = make_config(args)
    client = BaseBuilderApiClient(cfg.api_base, cfg.token)
    canonical_run_id = resolve_run_id(args.run_id)
    for event in client.attach_progress(canonical_run_id):
        data = compact_progress_data(event.data)
        if args.format == "ndjson":
            print(dumps(ok_envelope("runs.attach.progress", data, {"event": event.type, "runId": canonical_run_id})))
        else:
            print(f"{event.type}: {json.dumps(data, ensure_ascii=False)}")
    return 0


def cmd_artifact_manual(args: argparse.Namespace) -> int:
    artifact = artifact_from_report_or_run(args.run_id, args.from_report)
    path = write_manual(artifact, args.out)
    print(dumps(ok_envelope("artifacts.manual", {"path": str(path)})))
    return 0


def cmd_artifact_skill(args: argparse.Namespace) -> int:
    artifact = artifact_from_report_or_run(args.run_id, args.from_report)
    path = write_skill(artifact, args.out)
    print(dumps(ok_envelope("artifacts.skill", {"path": str(path)})))
    return 0


def cmd_report_generate(args: argparse.Namespace) -> int:
    artifact = artifact_for_run(args.run_id)
    report = build_report(args.run_id, artifact)
    path = write_report(report, args.out)
    save_run(args.run_id, {"report": report})
    print(dumps(ok_envelope("report.generate", {"path": str(path), "report": report}, {"runId": args.run_id})))
    return 0


def cmd_report_render(args: argparse.Namespace) -> int:
    report = read_report(args.report) if args.report else report_for_run(args.run_id)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report_markdown(report))
    print(dumps(ok_envelope("report.render", {"path": str(path)}, {"runId": args.run_id})))
    return 0


def cmd_lark_copy(args: argparse.Namespace) -> int:
    if args.copy_result:
        report = merge_copy_result(args.report, args.copy_result)
        save_run(args.run_id, {"report": report})
        print(dumps(ok_envelope("lark.copy", {"report": args.report, "copy": report.get("copy")}, {"runId": args.run_id})))
        return 0
    binary = require_larkcli()
    raise ApiError(
        "LARK_COPY_RESULT_REQUIRED",
        f"已找到 {binary}，但当前 CLI 需要 --copy-result 来合并复制后的 Base/table/field/view id map。",
        retryable=False,
    )


def cmd_skill_install(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser() if args.source else bundled_generic_skill_dir()
    if not (source / "SKILL.md").exists():
        raise ApiError("SKILL_SOURCE_INVALID", f"Skill source 缺少 SKILL.md: {source}", retryable=False)
    skill_name = read_skill_name(source / "SKILL.md") or ("basebuilder-cli" if not args.source else source.name)
    destination = Path(args.path).expanduser() if args.path else default_skill_install_dir(args.target, skill_name)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    print(dumps(ok_envelope("skill.install", {
        "source": str(source),
        "path": str(destination),
        "target": args.target,
        "nextSteps": [f"重启或刷新你的 agent，让它重新加载 {destination}。"],
    })))
    return 0


def cmd_ext_describe(args: argparse.Namespace) -> int:
    print(dumps(ok_envelope("ext.describe", describe_payload())))
    return 0


def cmd_ext_call(args: argparse.Namespace) -> int:
    payload = json.loads(args.input_json)
    if args.operation_name == "ext.describe":
        print(dumps(ok_envelope("ext.call", describe_payload(), {"called": args.operation_name})))
        return 0
    print(dumps(ok_envelope("ext.call", {"input": payload}, {"called": args.operation_name})))
    return 0


def artifact_for_run(run_id: str) -> dict[str, Any]:
    row = load_run(run_id)
    if isinstance(row.get("artifact"), dict):
        return row["artifact"]
    cfg = load_config()
    artifact = BaseBuilderApiClient(cfg.api_base, cfg.token).final_artifact(run_id)
    save_run(run_id, {"artifact": artifact})
    return artifact


def artifact_from_report_or_run(run_id: str, report_path: str = "") -> dict[str, Any]:
    if report_path:
        return materialize_report_artifact(read_report(report_path))
    return artifact_for_run(run_id)


def report_for_run(run_id: str) -> dict[str, Any]:
    row = load_run(run_id)
    if isinstance(row.get("report"), dict):
        return row["report"]
    return build_report(run_id, artifact_for_run(run_id))


def describe_payload() -> dict[str, Any]:
    return {
        "name": "basebuilder-cli",
        "version": __version__,
        "commands": COMMANDS,
        "formats": ["human", "json", "ndjson"],
        "intake": {
            "modes": ["text", "excel"],
            "structuredInput": ["json"],
            "templateFields": ["我想要构建", "我是", "业务场景", "痛点", "已有资料", "希望输出"],
            "pageTemplateFields": ["我想要构建", "我是/我们是", "主要使用者", "业务背景", "核心痛点", "已有资料", "希望输出", "约束", "参考案例", "背景知识"],
            "files": ["csv", "xlsx", "txt", "md"],
            "excel": "mode=excel requires at least one csv/xlsx file; multiple spreadsheet files are allowed",
            "refineFiles": "three-elements optimize can include multiple supporting files",
        },
        "artifacts": {
            "report": "report.json is the source for manual and per-Base Skill generation",
            "larkCopy": "copy metadata can be merged from local larkcli copy-result JSON",
        },
        "local_state": "~/.basebuilder",
        "api": {
            "base": "weave-ai-api",
            "default_base_url": DEFAULT_API_BASE,
            "production_login": DEFAULT_API_BASE,
            "production_port": 443,
            "local_dev_override": "Use --api-base or BB_API_BASE for http://127.0.0.1:8999 only during dev smoke.",
            "user_chain": "all user AI requests go through /api/cli endpoints",
            "agent_registration": {
                "production_base_url": DEFAULT_API_BASE,
                "intent": "agent_register",
                "client_kind": "agent",
                "fingerprint": "hash-only local fingerprint; raw MAC/hostname/username are not sent",
                "urls": ["verificationUrl", "loginUrl", "registerUrl", "rechargeUrl"],
                "authenticated_auto_register": "after basebuilder login, CLI upserts an agent identity without a second browser confirmation",
            },
        },
        "doctor": {
            "command": "basebuilder doctor --format json",
            "checks": ["api", "auth", "credits", "runs", "larkcli"],
            "status": ["ready", "ready_with_warnings", "needs_login", "offline", "no_credits"],
        },
    }


def register_agent_with_token(api_base: str, token: str, device_name: str) -> dict[str, Any]:
    fingerprint = build_fingerprint(state_dir())
    client = BaseBuilderApiClient(api_base, token)
    return client.agent_upsert(
        device_name=device_name,
        fingerprint_hash=str(fingerprint["fingerprint_hash"]),
        fingerprint_signals=dict(fingerprint["fingerprint_signals"]),
    )


def agent_registration_payload(session: dict[str, Any], fingerprint: dict[str, Any]) -> dict[str, Any]:
    verification_url = str(session.get("verificationUrl") or session.get("verification_url") or "")
    return {
        "intent": str(session.get("intent") or "agent_register"),
        "clientKind": str(session.get("clientKind") or session.get("client_kind") or "agent"),
        "userCode": str(session.get("userCode") or session.get("user_code") or ""),
        "verificationUrl": verification_url,
        "loginUrl": str(session.get("loginUrl") or session.get("login_url") or ""),
        "registerUrl": str(session.get("registerUrl") or session.get("register_url") or ""),
        "rechargeUrl": str(session.get("rechargeUrl") or session.get("recharge_url") or ""),
        "expiresAt": session.get("expiresAt") or session.get("expires_at"),
        "pollInterval": session.get("pollInterval") or session.get("poll_interval"),
        "fingerprintHash": str(fingerprint.get("fingerprint_hash") or ""),
    }


def make_config(args: argparse.Namespace) -> CliConfig:
    cfg = load_config()
    if getattr(args, "api_base", None):
        cfg.api_base = args.api_base.rstrip("/")
    return cfg


def read_prompt() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return read_line("请输入要搭建的业务系统需求: ").strip()


def read_template_input() -> dict[str, Any]:
    want_to_build = read_line("我想要构建: ").strip()
    role = read_line("我是/我们是: ").strip()
    primary_users = read_line("主要使用者(可选): ").strip()
    business_background = read_line("业务背景/当前流程(可选): ").strip()
    pain_points = parse_multi_value(read_line("核心痛点(多个用逗号分隔，可选): ").strip())
    existing_materials = read_line("已有资料(可选): ").strip()
    desired_outputs = parse_multi_value(read_line("希望输出(多个用逗号分隔，可选): ").strip())
    constraints = parse_multi_value(read_line("约束/不做(多个用逗号分隔，可选): ").strip())
    examples = parse_multi_value(read_line("参考案例(多个用逗号分隔，可选): ").strip())
    background = read_line("背景知识(可选): ").strip()
    return {
        "我想要构建": want_to_build,
        "我是": role,
        "主要使用者": primary_users,
        "业务背景": business_background,
        "核心痛点": pain_points,
        "已有资料": existing_materials,
        "希望输出": desired_outputs,
        "约束": constraints,
        "参考案例": examples,
        "背景知识": background,
    }


def run_interactive_create(client: BaseBuilderApiClient, prompt: str, fmt: str) -> tuple[CreateResult, bool]:
    analyze_response = client.analyze(prompt)
    elements = normalize_elements(analyze_response)
    message_id = extract_message_id(analyze_response)
    task_id = extract_task_id(analyze_response)
    emit_create_stage(fmt, "builds.analyze", elements.to_dict(), {"messageId": message_id, "taskId": task_id})

    while True:
        action = read_line("操作 [a]ccept / [e]dit / [o]ptimize / [q]uit: ").strip().lower()
        if action in {"a", "accept", "y", "yes"}:
            run = client.start_build(elements, message_id=message_id or None, task_id=task_id or None)
            run_id = str(run.get("runId") or run.get("run_id") or "")
            task_id = extract_task_id(run) or task_id
            emit_create_stage(fmt, "builds.create", {"status": "building", "runId": run_id, "run": run}, {
                "messageId": message_id,
                "taskId": task_id,
                "runId": run_id,
            })
            return CreateResult(status="building", elements=elements, run=run, message_id=message_id, task_id=task_id), fmt in {"human", "ndjson"}
        if action in {"e", "edit"}:
            elements = edit_elements(elements)
            emit_create_stage(fmt, "builds.edit", elements.to_dict(), {"messageId": message_id, "taskId": task_id})
            continue
        if action in {"o", "optimize"}:
            instruction = read_line("请输入优化方向: ").strip()
            file_text = read_line("可选补充文件路径(多个用逗号分隔，回车跳过): ").strip()
            refine_instruction = build_refine_instruction(instruction=instruction, files=parse_multi_value(file_text))
            optimize_response = client.optimize(elements, refine_instruction, message_id=message_id or None, task_id=task_id or None)
            elements = normalize_elements(optimize_response)
            message_id = extract_message_id(optimize_response) or message_id
            task_id = extract_task_id(optimize_response) or task_id
            emit_create_stage(fmt, "builds.optimize", elements.to_dict(), {"messageId": message_id, "taskId": task_id})
            continue
        if action in {"q", "quit", "n", "no", ""}:
            return CreateResult(status="needs_confirmation", elements=elements, run={}, message_id=message_id, task_id=task_id), fmt in {"human", "ndjson"}
        print("无法识别操作，请输入 a/e/o/q。", file=sys.stderr)


def edit_elements(elements: ThreeElements) -> ThreeElements:
    manage_what = read_line(f"管理对象 [{elements.manage_what}]: ").strip() or elements.manage_what
    workflow = read_line(f"流程 [{elements.workflow}]: ").strip() or elements.workflow
    fields = read_line(f"字段 [{elements.fields}]: ").strip() or elements.fields
    background = read_line(f"背景知识 [{elements.background_knowledge}]: ").strip() or elements.background_knowledge
    return ThreeElements(manage_what=manage_what, workflow=workflow, fields=fields, background_knowledge=background)


def emit_create_stage(fmt: str, operation: str, data: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
    if fmt == "ndjson":
        print(dumps(ok_envelope(operation, data, meta or {})))
        return
    stream = sys.stdout if fmt == "human" else sys.stderr
    if operation in {"builds.analyze", "builds.optimize", "builds.edit"}:
        print("AI 方案初稿 / 三要素:", file=stream)
        print("管理对象: " + str(data.get("manage_what") or ""), file=stream)
        print("流程: " + str(data.get("workflow") or ""), file=stream)
        print("字段: " + str(data.get("fields") or ""), file=stream)
        background = str(data.get("backgroundKnowledge") or data.get("background_knowledge") or "")
        if background:
            print("背景知识: " + background, file=stream)
        return
    print("状态: " + str(data.get("status") or ""), file=stream)
    if data.get("runId"):
        print("run_id: " + str(data["runId"]), file=stream)


def read_line(prompt: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    return input()


def parse_multi_value(text: str) -> list[str]:
    if not text.strip():
        return []
    normalized = text.replace("；", ",").replace("，", ",").replace("\n", ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def default_device_name() -> str:
    return f"{platform.node() or 'local'} / {platform.system()}"


def create_result_payload(result: CreateResult, run_id: str) -> dict[str, Any]:
    needs_confirmation = result.status == "needs_confirmation"
    payload: dict[str, Any] = {
        "status": result.status,
        "stage": "ai_blueprint_draft" if needs_confirmation else "building",
        "runId": run_id,
        "elements": result.elements.to_dict(),
        "run": result.run,
        "confirmationRequired": needs_confirmation,
        "nextSteps": [],
    }
    if needs_confirmation:
        payload["nextSteps"] = [
            f"向用户展示并确认方案后，运行 `basebuilder create confirm {run_id} --format json`。",
            "不要重新执行 create 或 create --auto-accept；确认必须恢复当前草稿的 message_id/task_id。",
            "如需修改 AI 方案初稿，使用 edit 或 optimize；optimize 可继续附加多个文件。",
        ]
    else:
        payload["nextSteps"] = [
            f"运行 `basebuilder runs inspect {run_id} --format json` 查看一次当前状态。",
        ]
    return payload


def find_matching_active_run(client: BaseBuilderApiClient, prompt: str) -> dict[str, Any] | None:
    active_statuses = {
        "building",
        "analyzing",
        "running",
        "started",
        "queued",
        "pending",
        "processing",
        "in_progress",
        "retrying",
    }
    for row in list_runs():
        if str(row.get("prompt") or "") != prompt:
            continue

        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        if str(row.get("status") or "").strip().lower() == "needs_confirmation":
            raise ApiError(
                "DRAFT_CONFIRMATION_REQUIRED",
                f"相同需求已有待确认草稿 {run_id}；请先向用户展示三要素，再运行 "
                f"`basebuilder create confirm {run_id} --format json`。本次没有创建新任务。",
                retryable=False,
            )
        try:
            snapshot = compact_progress_data(client.run_snapshot(run_id))
        except ApiError as exc:
            if exc.code == "RUN_NOT_FOUND":
                save_run(run_id, {
                    "status": "not_found",
                    "status_source": "server",
                })
                continue
            save_run(run_id, {
                "status": "unknown",
                "status_source": "server_unreachable",
                "status_error": {
                    "code": exc.code,
                    "message": str(exc),
                },
            })
            raise ApiError(
                "RUN_STATUS_UNAVAILABLE",
                "无法确认上一次任务的服务器状态。为避免重复创建和扣费，本次没有启动新任务；请稍后运行 runs inspect。",
                retryable=True,
            ) from exc

        status = str(snapshot.get("status") or "").strip().lower()
        updated = {
            **row,
            "snapshot": snapshot,
            "status": status or "unknown",
            "status_source": str(snapshot.get("statusSource") or "server"),
        }
        save_run(run_id, {
            "snapshot": snapshot,
            "status": updated["status"],
            "status_source": updated["status_source"],
        })
        if status in active_statuses:
            return updated
    return None


def emit_reused_active_run(fmt: str, row: dict[str, Any]) -> int:
    run_id = str(row.get("run_id") or "")
    data = {
        "status": str(row.get("status") or "building"),
        "stage": "building",
        "runId": run_id,
        "messageId": int(row.get("message_id") or 0),
        "taskId": str(row.get("task_id") or ""),
        "reused": True,
        "duplicatePrevented": True,
        "nextSteps": [
            f"运行 `basebuilder runs inspect {run_id} --format json` 查看一次当前状态。",
        ],
    }
    if fmt in {"json", "ndjson"}:
        print(dumps(ok_envelope("builds.create", data, {
            "runId": run_id,
            "messageId": data["messageId"],
            "taskId": data["taskId"],
        })))
    else:
        print("检测到相同需求已有进行中的任务，已阻止重复创建和重复扣费。")
        print("run_id: " + run_id)
        print(f"查看一次状态: basebuilder runs inspect {run_id} --format json")
    return 0


def print_post_build_guidance(run_id: str, progress: dict[str, Any]) -> None:
    base_url = str(progress.get("baseUrl") or "")
    status = str(progress.get("status") or progress.get("state") or "").lower()
    if not base_url or status not in {"success", "succeeded", "completed", "complete"}:
        return
    print("")
    print("下一步:")
    print(f"- 请先检查生成的多维表: {base_url}")
    print("- 如果认可该表，再把它转移到自己的 Feishu/Lark 空间：")
    print(f"  basebuilder report generate {run_id} --out ./report.json")
    print(f"  basebuilder lark copy {run_id} --report ./report.json --copy-result ./copy-result.json")
    print("- 转移完成后，确认是否让自己的 agent 学习这个表怎么用；确认后生成 report 和该表专用 Skill：")
    print(f"  basebuilder artifacts skill {run_id} --from-report ./report.json --out ./base-skill")
    print("  basebuilder skill install --source ./base-skill --target codex")


def bundled_generic_skill_dir() -> Path:
    repo_skill = Path(__file__).resolve().parents[2] / "skills" / "basebuilder-cli"
    if (repo_skill / "SKILL.md").exists():
        return repo_skill
    package_skill = Path(__file__).resolve().parent / "resources" / "basebuilder-cli"
    return package_skill


def default_skill_install_dir(target: str, skill_name: str = "basebuilder-cli") -> Path:
    safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in skill_name).strip("-") or "basebuilder-cli"
    if target == "agents":
        return Path(f"~/.agents/skills/{safe_name}").expanduser()
    return Path(f"~/.codex/skills/{safe_name}").expanduser()


def read_skill_name(path: Path) -> str:
    for line in path.read_text(errors="ignore").splitlines()[:20]:
        if line.startswith("name: "):
            return line.split(":", 1)[1].strip()
    return ""


def emit(fmt: str, operation: str, data: Any, *, human: str) -> int:
    if fmt == "json":
        print(dumps(ok_envelope(operation, data)))
    else:
        print(human)
    return 0


def compact_progress_data(data: dict[str, Any]) -> dict[str, Any]:
    raw = unwrap_progress_payload(data)
    last_event = last_answer_event(raw)
    delivery = first_mapping(raw.get("delivery"), last_event.get("delivery"))
    delivery_data = first_mapping(delivery.get("data"))
    snapshot = first_mapping(raw.get("snapshot"))
    request = first_mapping(raw.get("request"))

    result: dict[str, Any] = {}
    copy_first(result, "status", request, raw, last_event, keys=["status", "state", "queue_state"])
    copy_first(result, "state", raw, last_event, keys=["state", "queue_state"])
    copy_first(result, "progress", raw, last_event, keys=["progress"])
    copy_first(result, "currentStep", raw, last_event, keys=["current_step", "step"])
    copy_first(result, "lastSuccessStep", raw, keys=["last_success_step"])
    copy_first(result, "message", raw, last_event, keys=["message", "description", "last_message"])
    copy_first(result, "taskId", raw, keys=["task_id", "taskId"])
    copy_first(result, "messageId", raw, keys=["message_id", "messageId"])
    copy_first(result, "requestId", request, raw, keys=["request_id", "requestId"])
    copy_first(result, "buildRunId", request, raw, last_event, keys=["run_id", "buildRunId"])
    copy_first(result, "statusSource", raw, keys=["statusSource", "status_source"])
    copy_first(result, "baseUrl", raw, delivery_data, snapshot, keys=["baseUrl", "base_url", "url", "app_url", "feishu_url"])
    copy_first(result, "tableName", raw, delivery_data, snapshot, keys=["table_name", "tableName", "name"])

    cursor = first_mapping(raw.get("snapshot_cursor"))
    if cursor:
        result["cursor"] = {
            key: cursor[key]
            for key in ("event_seq", "artifact_version", "action_seq")
            if key in cursor
        }

    artifact_counts = first_mapping(raw.get("artifact_counts"))
    normalized_counts = first_mapping(raw.get("artifactCounts"))
    by_type = first_mapping(artifact_counts.get("by_type"), normalized_counts)
    if by_type:
        result["artifactCounts"] = {
            key: by_type.get(key, 0)
            for key in ("table", "field", "view", "record", "record_batch")
            if key in by_type
        }
        if "total" in artifact_counts:
            result["artifactCounts"]["total"] = artifact_counts["total"]

    ready = first_mapping(delivery.get("ready"), raw.get("delivery_ready"))
    if ready:
        result["deliveryReady"] = {
            key: ready[key]
            for key in ("table_name", "url", "mermaid")
            if key in ready
        }

    if not result:
        return {key: value for key, value in data.items() if key not in {"answer_text", "problem_text"}}
    if not request:
        normalize_finalized_delivery(result)
    return result


def unwrap_progress_payload(data: dict[str, Any]) -> dict[str, Any]:
    raw = data
    for _ in range(6):
        nested = raw.get("data") if isinstance(raw.get("data"), dict) else None
        if not nested:
            break
        nested_has_progress = any(key in nested for key in (
            "status",
            "state",
            "queue_state",
            "current_step",
            "last_success_step",
            "snapshot",
            "answer_text",
            "delivery",
            "artifact_counts",
        ))
        raw_is_envelope = any(key in raw for key in ("ok", "success", "operation", "code"))
        if nested_has_progress or raw_is_envelope:
            raw = nested
            continue
        break
    return raw


def normalize_finalized_delivery(result: dict[str, Any]) -> None:
    last_success = str(result.get("lastSuccessStep") or "")
    status = str(result.get("status") or "").lower()
    has_delivery = bool(result.get("baseUrl") and result.get("tableName"))
    counts = result.get("artifactCounts")
    has_schema_artifacts = isinstance(counts, dict) and any(int(counts.get(key) or 0) > 0 for key in ("table", "field", "view"))

    if last_success == "fast_build.finalize" and has_delivery and status in {"", "failed", "failure", "error", "processing"}:
        result["status"] = "success"
        result["currentStep"] = "fast_build.finalize"
        result.setdefault("message", "完成搭建")
        if has_schema_artifacts:
            result["progress"] = 100


def last_answer_event(data: dict[str, Any]) -> dict[str, Any]:
    answer = data.get("answer_text")
    if not isinstance(answer, list):
        return {}
    for item in reversed(answer):
        if isinstance(item, dict):
            return item
    return {}


def first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def copy_first(
    result: dict[str, Any],
    output_key: str,
    *sources: dict[str, Any],
    keys: list[str],
) -> None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                result[output_key] = value
                return


def print_progress_event(event_type: str, data: dict[str, Any]) -> None:
    progress = data.get("progress")
    message = data.get("message") or data.get("last_message") or data.get("status") or data.get("state") or ""
    prefix = f"{event_type}"
    if progress not in (None, ""):
        prefix += f" {progress}%"
    extras: list[str] = []
    if data.get("baseUrl"):
        extras.append(str(data["baseUrl"]))
    counts = data.get("artifactCounts")
    if isinstance(counts, dict):
        count_parts = [
            f"{label}={counts[key]}"
            for key, label in (("table", "tables"), ("field", "fields"), ("view", "views"))
            if key in counts
        ]
        if count_parts:
            extras.append("summary " + " ".join(count_parts))
    if message:
        suffix = (" | " + " | ".join(extras)) if extras else ""
        print(f"{prefix}: {message}{suffix}")
    else:
        suffix = (": " + " | ".join(extras)) if extras else ""
        print(prefix + suffix)


if __name__ == "__main__":
    raise SystemExit(main())
