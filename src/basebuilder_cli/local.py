import json
import os
import re
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from .client import ApiError
from .intake import build_intake_prompt
from .protocol import dumps, ok_envelope


def failure(message):
    return ApiError("LOCAL_REVIEW_REQUIRED", message)


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,179}", value):
        raise failure("本地任务标识无效")
    return value


def origin_url(value):
    if not isinstance(value, str) or not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", value) or int(value.rsplit(":", 1)[1]) > 65535:
        raise failure("本地模式必须显式指定 http://127.0.0.1:端口")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise failure("本地服务禁止HTTP重定向")


class LocalClient:
    def __init__(self, origin):
        self.origin = origin_url(origin)
        token_file = os.environ.get("BB_LOCAL_TOKEN_FILE", "")
        if not token_file or not Path(token_file).is_absolute():
            raise failure("必须显式配置本地专用鉴权文件")
        self.token = Path(token_file).read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", self.token):
            raise failure("本地鉴权文件无效")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.service_id = None

    def request(self, method, path, data=None):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if self.service_id is not None:
            headers["X-BaseBuilder-Service-Id"] = self.service_id
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=True, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            if len(body) > 256 * 1024:
                raise failure("本地请求内容过大")
        request = urllib.request.Request(self.origin + path, data=body, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise failure("本地服务回执过大")
            value = json.loads(raw)
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise failure("本地服务请求未完成，请保留原请求并核对服务，勿重复生成") from error
        if not isinstance(value, dict) or value.get("ok") is not True or not isinstance(value.get("data"), dict):
            raise failure("本地服务回执无效")
        result = value["data"]
        if self.service_id is not None and result.get("serviceId") != self.service_id:
            raise failure("本地服务身份已变化，禁止复用原任务")
        return result

    def capabilities(self):
        value = self.request("GET", "/api/local/capabilities")
        if not value.get("serviceId") or value.get("designOnly") is not True or value.get("schema") != "basebuilder.system-design/v1":
            raise failure("本地服务不支持仅设计合同")
        self.service_id = value["serviceId"]
        return value

    def inspect(self, request_id, operation):
        value = self.request("GET", "/api/local/requests/" + valid_id(request_id))
        return self.receipt(value, request_id, operation)

    def submit(self, request_id, operation, data):
        value = self.request("POST", "/api/local/requests", {"requestId": valid_id(request_id), "operation": operation, "input": data})
        return self.receipt(value, request_id, operation)

    def receipt(self, value, request_id, operation):
        if value.get("requestId") != request_id or value.get("operation") != operation or value.get("status") not in {"queued", "running", "succeeded", "failed", "interrupted"}:
            raise failure("本地回执与原请求不一致")
        return value


def read_json(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise failure("本地文件过大")
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def complete_elements(value):
    keys = ("manage_what", "workflow", "fields")
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not value[key].strip() for key in keys):
        raise failure("本地三要素不完整")
    return value


def dispatch(args):
    home = os.environ.get("BB_LOCAL_HOME", "")
    if not home or not Path(home).is_absolute():
        raise failure("必须显式配置独立本地任务目录 BB_LOCAL_HOME")
    directory = Path(home)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "cli.lock").open("a+b") as lock:
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise failure("本地CLI已有请求执行，请等待后查询原任务") from error
        try:
            return dispatch_locked(args)
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def dispatch_locked(args):
    origin = origin_url(args.api_base)
    if args.command not in {"doctor", "health", "create", "design", "runs"}:
        raise failure("本地模式不支持网页登录、飞书构建或扩展命令")
    if args.command == "create" and (args.create_action == "confirm" or args.auto_accept or args.wait or args.file or args.mode != "text"):
        raise failure("本地模式只整理需求和设计，不执行飞书构建或文件导入")
    if args.command == "runs" and args.runs_command not in {"list", "inspect"}:
        raise failure("本地模式不支持此任务操作")
    home = os.environ.get("BB_LOCAL_HOME", "")
    if not home or not Path(home).is_absolute():
        raise failure("必须显式配置独立本地任务目录 BB_LOCAL_HOME")
    directory = Path(home) / "runs"
    client = LocalClient(origin)
    capability = client.capabilities()
    backend = {"origin": origin, "serviceId": capability["serviceId"]}

    def load(run_id):
        value = read_json(directory / (valid_id(run_id) + ".json"))
        if value.get("backend") != backend:
            raise failure("本地任务绑定了其他服务，不能切换目标恢复")
        return value

    def persist(row):
        save(directory / (valid_id(row["runId"]) + ".json"), row)

    def wait(request_id, operation, response):
        end = time.monotonic() + 150
        while response["status"] in {"queued", "running"}:
            if time.monotonic() >= end:
                raise failure("本地请求仍在执行，保留原任务并查询状态，勿重新生成")
            time.sleep(.2)
            response = client.inspect(request_id, operation)
        if response["status"] != "succeeded":
            raise failure("原本地请求失败或中断，需人工核对，不会重新调用模型")
        return response["result"]

    if args.command in {"doctor", "health"}:
        data = {"mode": "local", **capability, "summary": {"usable": True, "status": "ready", "message": "本地仅设计服务已连接，无需网页登录；模型能力需实际生成验证"}}
    elif args.command == "create":
        if args.create_action == "optimize":
            row = load(args.draft_run_id)
            if args.prompt or args.input or not args.instruction.strip() or len(args.instruction) > 8000 or row.get("designRequestId"):
                raise failure("只有未确认的本地草稿可以按明确意见优化")
            previous = row.get("completedOptimizations", {}).get(args.request_id) if args.request_id else None
            if previous:
                if previous["instruction"] != args.instruction.strip() or previous["elements"] != row["elements"]:
                    raise failure("原优化请求已完成且草稿已变化，不会替换或重新生成")
                print(dumps(ok_envelope("local.create", {"runId": row["runId"], "elements": row["elements"], "confirmationRequired": True, "serviceId": capability["serviceId"]})))
                return 0
            data_input = {"elements": row["elements"], "instruction": args.instruction.strip()}
            pending = row.get("pendingOptimize")
            if pending and pending["input"] != data_input:
                raise failure("原优化请求仍待核对，不可替换请求内容")
            if pending is None:
                pending = {"requestId": args.request_id or str(uuid.uuid4()), "input": data_input}
                row["pendingOptimize"] = pending
                persist(row)
            response = client.submit(pending["requestId"], "optimize", pending["input"])
            row["elements"] = complete_elements(wait(pending["requestId"], "optimize", response)["elements"])
            row.setdefault("completedOptimizations", {})[pending["requestId"]] = {"instruction": args.instruction.strip(), "elements": row["elements"]}
            del row["pendingOptimize"]
            persist(row)
        else:
            prompt = build_intake_prompt(prompt=args.prompt, input_path=args.input)
            request_id = args.request_id or str(uuid.uuid4())
            run_id = "local-" + valid_id(request_id)
            path = directory / (run_id + ".json")
            if path.exists():
                row = load(run_id)
                if row["prompt"] != prompt:
                    raise failure("原分析请求已绑定不同需求")
            else:
                row = {"runId": run_id, "backend": backend, "prompt": prompt, "requestId": request_id, "status": "analyzing"}
                persist(row)
            if not row.get("elements"):
                response = client.submit(request_id, "analyze", {"prompt": prompt})
                row["elements"] = complete_elements(wait(request_id, "analyze", response)["elements"])
                row["status"] = "needs_confirmation"
                persist(row)
        data = {"runId": row["runId"], "elements": row["elements"], "confirmationRequired": True, "serviceId": capability["serviceId"]}
    elif args.command == "design":
        row = load(args.draft_run_id)
        request_id = valid_id(args.request_id)
        if args.design_action == "draft":
            context = read_json(Path(args.input))
            if not isinstance(context, dict) or set(context) != {"runId", "elements", "intake", "sourceSignature"} or context["runId"] != row["runId"] or context["elements"] != row.get("elements") or row.get("pendingOptimize"):
                raise failure("详细设计必须使用原草稿的已确认三要素和上下文")
            if row.get("designRequestId") and (row["designRequestId"] != request_id or row["designInput"] != context):
                raise failure("原设计请求已绑定不同内容，不会重新生成")
            row.update(designRequestId=request_id, designInput=context)
            persist(row)
            response = client.submit(request_id, "design", context)
        else:
            if row.get("designRequestId") != request_id:
                raise failure("原草稿未绑定该设计请求")
            response = client.inspect(request_id, "design")
        data = {"runId": row["runId"], "requestId": request_id, "status": response["status"], "serviceId": capability["serviceId"]}
        if response["status"] == "succeeded":
            result = response.get("result", {})
            if result.get("runId") != row["runId"] or not isinstance(result.get("design"), dict):
                raise failure("设计结果与原草稿不一致")
            data["design"] = result["design"]
    elif args.runs_command == "list":
        data = {"items": [value for path in directory.glob("*.json") if (value := read_json(path)).get("backend") == backend]}
    else:
        data = load(args.run_id)
        request_id = data.get("designRequestId") or data.get("requestId")
        if request_id:
            data = {**data, "snapshot": client.inspect(request_id, "design" if data.get("designRequestId") else "analyze")}
    print(dumps(ok_envelope("local." + args.command, data)))
    return 0
