import io
import json
import os
import secrets
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from basebuilder_cli.client import ApiError
from basebuilder_cli.cli import main
from basebuilder_cli.local import LocalClient, origin_url, safe_design_error


EXECUTION_REASONS = ("authentication", "permission_denied", "connection", "timeout", "rate_limit",
                     "response_parse", "invalid_request", "runtime", "unknown")


class ExecutionDiagnosticTest(unittest.TestCase):
    def test_execution_diagnostics_accept_both_stages_and_ignore_messages(self):
        for stage in ("initialization", "execution"):
            for reason in EXECUTION_REASONS:
                safe = {"code": "LOCAL_DESIGN_EXECUTION_FAILED", "stage": stage, "reason": reason}
                for message in ("SECRET-MESSAGE", None, [], {"raw": "SECRET-MESSAGE"}):
                    with self.subTest(stage=stage, reason=reason, message=message):
                        self.assertEqual(safe_design_error({"status": "failed", "error": {
                            **safe, "message": message}}), safe)
                        self.assertEqual(safe_design_error({"status": "interrupted", "error": safe}),
                                         {"code": "LOCAL_REVIEW_REQUIRED"})

    def test_execution_diagnostics_reject_paths_unknown_keys_and_cross_code_pairs(self):
        code_only = {"code": "LOCAL_DESIGN_EXECUTION_FAILED"}
        for stage in ("initialization", "execution"):
            safe = {**code_only, "stage": stage, "reason": "connection"}
            invalid = [
                *({**safe, "paths": paths} for paths in ([], None, ["name"], "name", {})),
                *({**safe, key: "SECRET"} for key in ("raw", "input", "ctx", "extra")),
                *({**safe, "reason": reason} for reason in (None, [], {}, "invalid_json", "SECRET")),
                {**code_only, "stage": stage}, {**code_only, "reason": "connection"},
            ]
            for error in invalid:
                with self.subTest(error=error):
                    self.assertEqual(safe_design_error({"status": "failed", "error": error}), code_only)
            for code in ("LOCAL_DESIGN_OUTPUT_INVALID", "LOCAL_EXECUTION_FAILED", "LOCAL_REVIEW_REQUIRED"):
                for reason in EXECUTION_REASONS:
                    with self.subTest(code=code, stage=stage, reason=reason):
                        self.assertEqual(safe_design_error({"status": "failed", "error": {
                            "code": code, "stage": stage, "reason": reason}}), {"code": code})
        for stage in ("json", "contract", "platform", "SECRET", None, [], {}):
            self.assertEqual(safe_design_error({"status": "failed", "error": {
                **code_only, "stage": stage, "reason": "connection"}}), code_only)
        self.assertEqual(safe_design_error({"status": "failed", "error": code_only}), code_only)


class LocalHttpTest(unittest.TestCase):
    def test_real_http_draft_optimize_design_and_restore(self):
        calls = []
        elements = {"manage_what": "客户", "workflow": "录入到跟进", "fields": "名称"}
        updated = {**elements, "fields": "名称和阶段"}
        requests = {}
        token = secrets.token_hex(32)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def reply(self, data):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "data": {"serviceId": "service-test", **data}}).encode())
            def do_GET(self):
                self.assert_auth()
                if self.path == "/api/local/capabilities":
                    self.reply({"designOnly": True, "schema": "basebuilder.system-design/v1"})
                else:
                    self.reply(requests[self.path.rsplit("/", 1)[1]])
            def assert_auth(self):
                if self.headers.get("Authorization") != "Bearer " + token:
                    raise AssertionError("未使用独立本地token")
            def do_POST(self):
                self.assert_auth()
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(body)
                operation = body["operation"]
                result = {"elements": elements if operation == "analyze" else updated} if operation != "design" else {"runId": body["input"]["runId"], "design": {"schema": "basebuilder.system-design/v1"}}
                response = {"requestId": body["requestId"], "operation": operation, "status": "succeeded", "result": result}
                requests[body["requestId"]] = response
                self.reply(response)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                (path / "token").write_text(token, encoding="utf-8")
                env = {"BB_LOCAL_HOME": directory, "BB_LOCAL_TOKEN_FILE": str(path / "token"), "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"}
                base = ["--local-dev", "--api-base", f"http://127.0.0.1:{server.server_port}"]
                def run(args):
                    with redirect_stdout(io.StringIO()) as out:
                        code = main(base + args)
                    self.assertEqual(code, 0, out.getvalue())
                    return json.loads(out.getvalue())["data"]
                with patch.dict(os.environ, env), patch("basebuilder_cli.cli.load_config", side_effect=AssertionError("不读取线上token")):
                    self.assertTrue(run(["doctor", "--format", "json"])["summary"]["usable"])
                    draft = run(["create", "--prompt", "客户管理", "--request-id", "analyze-1", "--format", "json"])
                    self.assertEqual(draft["elements"], elements)
                    run(["create", "--prompt", "客户管理", "--request-id", "analyze-1", "--format", "json"])
                    optimized = run(["create", "optimize", draft["runId"], "--instruction", "增加阶段", "--request-id", "optimize-1", "--format", "json"])
                    self.assertEqual(run(["create", "optimize", draft["runId"], "--instruction", "增加阶段", "--request-id", "optimize-1", "--format", "json"]), optimized)
                    self.assertEqual(optimized["elements"], updated)
                    context = {"runId": draft["runId"], "elements": updated, "intake": {}, "sourceSignature": "source"}
                    (path / "context.json").write_text(json.dumps(context), encoding="utf-8")
                    command = [draft["runId"], "--request-id", "design-1", "--format", "json"]
                    designed = run(["design", "draft", *command, "--input", str(path / "context.json")])
                    self.assertEqual(designed["status"], "succeeded")
                    self.assertEqual(run(["design", "inspect", *command]), designed)
                    self.assertEqual([call["operation"] for call in calls], ["analyze", "optimize", "design"])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_redirects_never_forward_credentials_or_submit_to_target(self):
        forwarded = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def handle_request(self):
                if self.path == "/target":
                    forwarded.append((self.command, dict(self.headers)))
                    self.send_response(200)
                else:
                    code, target = self.path.strip("/").split("/")
                    self.send_response(int(code))
                    self.send_header("Location", target_origin + "/target" if target == "other" else "/target")
                self.end_headers()
            do_GET = handle_request
            do_POST = handle_request
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        target = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        target_origin = f"http://127.0.0.1:{target.server_port}"
        threads = [threading.Thread(target=item.serve_forever) for item in (server, target)]
        for thread in threads:
            thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                token_file = Path(directory) / "token"
                token_file.write_text(secrets.token_hex(32), encoding="utf-8")
                with patch.dict(os.environ, {"BB_LOCAL_TOKEN_FILE": str(token_file)}):
                    client = LocalClient(f"http://127.0.0.1:{server.server_port}")
                    for code in (301, 302, 303, 307, 308):
                        for destination in ("same", "other"):
                            for method in ("GET", "POST"):
                                with self.subTest(code=code, destination=destination, method=method):
                                    with self.assertRaises(ApiError) as error:
                                        client.request(method, f"/{code}/{destination}", {} if method == "POST" else None)
                                    self.assertEqual(error.exception.code, "LOCAL_REVIEW_REQUIRED")
                    self.assertEqual(forwarded, [])
        finally:
            for item in (server, target):
                item.shutdown()
            for thread in threads:
                thread.join()
            for item in (server, target):
                item.server_close()

    def test_strict_origin_variants(self):
        for value in ["http://localhost:8999", "http://127.1:8999", "http://127.0.0.1:8999/", "http://user@127.0.0.1:8999", "http://127.0.0.1:8999?x=1", "http://127.0.0.1:65536"]:
            with self.subTest(value=value), self.assertRaises(Exception):
                origin_url(value)


class PlatformDesignHttpTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.requests = {}
        self.capability = {"designOnly": True, "schema": "basebuilder.system-design/v1",
                           "platformDesignSchema": "basebuilder.platform-design/v1", "platforms": ["feishu"]}
        self.elements = {"manage_what": "客户", "workflow": "录入到跟进", "fields": "名称"}
        self.receipt_platform = "feishu"
        self.receipt_schema = "basebuilder.platform-design/v1"
        self.design_status = "succeeded"
        self.design_error = None
        token = secrets.token_hex(32)
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, data):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "data": {"serviceId": "platform-service", **data}}).encode())

            def assert_auth(self):
                if self.headers.get("Authorization") != "Bearer " + token:
                    raise AssertionError("未使用独立本地token")

            def do_GET(self):
                self.assert_auth()
                if self.path == "/api/local/capabilities":
                    self.reply(fixture.capability)
                else:
                    self.reply(fixture.requests[self.path.rsplit("/", 1)[1]])

            def do_POST(self):
                self.assert_auth()
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fixture.calls.append(body)
                operation = body["operation"]
                result = {"elements": fixture.elements} if operation == "analyze" else {
                    "runId": body["input"]["runId"],
                    "design": {"schema": fixture.receipt_schema, "platform": fixture.receipt_platform}}
                response = {"requestId": body["requestId"], "operation": operation,
                            "status": "succeeded" if operation == "analyze" else fixture.design_status,
                            "result": result}
                if operation != "analyze" and fixture.design_error is not None:
                    response["error"] = fixture.design_error
                fixture.requests[body["requestId"]] = response
                self.reply(response)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever)
        thread.start()

        def close_server():
            self.server.shutdown()
            thread.join()
            self.server.server_close()

        self.addCleanup(close_server)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        (self.path / "token").write_text(token, encoding="utf-8")
        env = {key: str(self.path) for key in ("HOME", "USERPROFILE", "BB_HOME", "BB_LOCAL_HOME")}
        env["BB_LOCAL_TOKEN_FILE"] = str(self.path / "token")
        self.enterContext(patch.dict(os.environ, env))
        self.enterContext(patch("basebuilder_cli.cli.load_config", side_effect=AssertionError("不读取线上配置")))
        self.draft = self.run_cli(["create", "--prompt", "客户管理", "--request-id", "platform-analyze"])
        self.context = {"runId": self.draft["runId"], "elements": self.elements, "intake": {"source": "confirmed"},
                        "sourceSignature": "platform-source", "platform": "feishu"}
        self.command = [self.draft["runId"], "--request-id", "platform-design"]

    def run_cli(self, args, expected=0):
        base = ["--local-dev", "--api-base", f"http://127.0.0.1:{self.server.server_port}"]
        with redirect_stdout(io.StringIO()) as out:
            code = main(base + args + ["--format", "json"])
        self.assertEqual(code, expected, out.getvalue())
        envelope = json.loads(out.getvalue())
        if expected:
            self.assertIn("LOCAL_REVIEW_REQUIRED", out.getvalue())
            return envelope
        return envelope["data"]

    def submit_design(self, expected=0):
        context_path = self.path / "context.json"
        context_path.write_text(json.dumps(self.context), encoding="utf-8")
        return self.run_cli(["design", "draft", *self.command, "--input", str(context_path)], expected)

    def saved_row(self):
        return json.loads((self.path / "runs" / (self.draft["runId"] + ".json")).read_text(encoding="utf-8"))

    def fork_design(self, request_id="stable-fork", expected=0, source=None):
        with patch.object(LocalClient, "submit", side_effect=AssertionError("fork 不提交请求")) as submit, \
                patch.object(LocalClient, "inspect", side_effect=AssertionError("fork 不查询请求")) as inspect:
            try:
                result = self.run_cli(["design", "fork", source or self.draft["runId"],
                                       "--request-id", request_id], expected)
            except SystemExit as error:
                self.fail(f"design fork 应被 parser 接受，实际退出 {error.code}")
            submit.assert_not_called()
            inspect.assert_not_called()
        return result

    def test_fork_copies_only_confirmed_content_without_submitting_or_changing_source(self):
        self.submit_design()
        original_path = self.path / "runs" / (self.draft["runId"] + ".json")
        original = self.saved_row()
        original.update(status="succeeded", design={"old": True},
                        completedOptimizations={"old-optimize": {"instruction": "旧意见"}})
        original_path.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")
        before = original_path.read_bytes()
        calls_before = list(self.calls)
        fork = self.fork_design()
        self.assertEqual(fork["runId"], "local-fork-stable-fork")
        self.assertEqual(fork["elements"], self.elements)
        self.assertIs(fork["confirmationRequired"], True)
        target = self.path / "runs" / (fork["runId"] + ".json")
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {
            "runId": fork["runId"], "backend": original["backend"], "prompt": original["prompt"],
            "elements": self.elements, "status": "needs_confirmation", "forkedFrom": self.draft["runId"]})
        self.assertEqual(original_path.read_bytes(), before)
        self.assertEqual(self.calls, calls_before)

    def test_fork_retry_preserves_existing_target_even_after_new_design_binding(self):
        self.submit_design()
        source_path = self.path / "runs" / (self.draft["runId"] + ".json")
        before = source_path.read_bytes()
        fork = self.fork_design()
        target = self.path / "runs" / (fork["runId"] + ".json")
        pristine = target.read_bytes()
        self.assertEqual(self.fork_design(), fork)
        self.assertEqual(target.read_bytes(), pristine)
        self.capability["platforms"].append("dingtalk")
        self.receipt_platform = "dingtalk"
        context_path = self.path / "fork-context.json"
        context_path.write_text(json.dumps({**self.context, "runId": fork["runId"], "platform": "dingtalk"}), encoding="utf-8")
        self.run_cli(["design", "draft", fork["runId"], "--request-id", "fork-new-design",
                      "--input", str(context_path)])
        bound = target.read_bytes()
        calls_before = list(self.calls)
        self.assertEqual(self.fork_design(), fork)
        self.assertEqual(target.read_bytes(), bound)
        self.assertEqual(source_path.read_bytes(), before)
        self.assertEqual(self.calls, calls_before)
        self.assertEqual(self.run_cli(["design", "inspect", *self.command])["design"]["platform"], "feishu")

    def test_fork_rejects_unbound_incomplete_pending_or_foreign_source(self):
        self.submit_design()
        original = self.saved_row()
        source_path = self.path / "runs" / (self.draft["runId"] + ".json")
        invalid_rows = [
            {key: value for key, value in original.items() if key != "designInput"},
            {key: value for key, value in original.items() if key != "designRequestId"},
            {**original, "designInput": {key: value for key, value in self.context.items() if key != "platform"}},
            {**original, "elements": {**self.elements, "fields": " "}},
            {**original, "pendingOptimize": {"requestId": "pending"}},
            {**original, "backend": {**original["backend"], "serviceId": "other-service"}},
        ]
        calls_before = list(self.calls)
        for row in invalid_rows:
            with self.subTest(row=row):
                source_path.write_text(json.dumps(row, indent=2), encoding="utf-8")
                before = source_path.read_bytes()
                self.fork_design(expected=1)
                self.assertEqual(source_path.read_bytes(), before)
                self.assertFalse((self.path / "runs" / "local-fork-stable-fork.json").exists())
        self.assertEqual(self.calls, calls_before)

    def test_fork_rejects_target_identity_content_and_backend_conflicts_without_overwrite(self):
        self.submit_design()
        original = self.saved_row()
        source_path = self.path / "runs" / (self.draft["runId"] + ".json")
        source_before = source_path.read_bytes()
        fork = self.fork_design()
        target = self.path / "runs" / (fork["runId"] + ".json")
        saved = json.loads(target.read_text(encoding="utf-8"))
        for key, value in (("backend", {**saved["backend"], "serviceId": "other"}),
                           ("runId", "local-other"), ("forkedFrom", "local-other"),
                           ("prompt", "不同需求"), ("elements", {**self.elements, "fields": "不同字段"})):
            with self.subTest(key=key):
                target.write_text(json.dumps({**saved, key: value}, indent=2), encoding="utf-8")
                before = target.read_bytes()
                self.fork_design(expected=1)
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(source_path.read_bytes(), source_before)
        target.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        before = target.read_bytes()
        other = {**original, "runId": "local-other-source",
                 "designInput": {**self.context, "runId": "local-other-source"}}
        (self.path / "runs" / "local-other-source.json").write_text(json.dumps(other), encoding="utf-8")
        self.fork_design(source=other["runId"], expected=1)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(source_path.read_bytes(), source_before)

    def test_fork_validates_full_run_id_and_online_rejects_before_connecting(self):
        self.submit_design()
        source_path = self.path / "runs" / (self.draft["runId"] + ".json")
        before = source_path.read_bytes()
        existing = set((self.path / "runs").iterdir())
        for request_id in ("../escape", "bad.id", "x" * 170, "x" * 181):
            with self.subTest(request_id=request_id):
                self.fork_design(request_id, expected=1)
                self.assertEqual(set((self.path / "runs").iterdir()), existing)
                self.assertEqual(source_path.read_bytes(), before)
        boundary = self.fork_design("x" * 169)
        self.assertEqual(len(boundary["runId"]), 180)
        with patch("basebuilder_cli.cli.BaseBuilderApiClient", side_effect=AssertionError("不连接线上")) as online, \
                patch("basebuilder_cli.local.dispatch", side_effect=AssertionError("不进入本地分发")) as dispatch, \
                redirect_stdout(io.StringIO()) as out:
            try:
                code = main(["design", "fork", self.draft["runId"], "--request-id", "online-fork"])
            except SystemExit as error:
                self.fail(f"online fork 应返回本地专属错误，实际 parser 退出 {error.code}")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "LOCAL_MODE_REQUIRED")
        online.assert_not_called()
        dispatch.assert_not_called()
        self.assertFalse((self.path / "runs" / "local-fork-online-fork.json").exists())

    def prepare_recovery(self):
        self.submit_design()
        fork = self.fork_design()
        self.recovery_path = self.path / "runs" / (fork["runId"] + ".json")
        self.recovery_context = {**self.context, "runId": fork["runId"]}
        self.recovery_input = self.path / "recovery-context.json"
        self.recovery_command = [fork["runId"], "--request-id", "recovery-design"]
        return fork

    def recover(self, action, expected=0, context=None, with_input=True, command=None):
        args = ["design", action, *(command or self.recovery_command)]
        if with_input:
            self.recovery_input.write_text(json.dumps(self.recovery_context if context is None else context), encoding="utf-8")
            args.extend(["--input", str(self.recovery_input)])
        try:
            return self.run_cli(args, expected)
        except SystemExit as error:
            self.fail(f"design {action} 应被 parser 接受，实际退出 {error.code}")

    def test_recovery_inspect_unbound_fork_returns_evidence_without_binding_or_http(self):
        fork = self.prepare_recovery()
        before = self.recovery_path.read_bytes()
        with patch.object(LocalClient, "submit") as submit, patch.object(LocalClient, "inspect") as inspect:
            self.assertEqual(self.recover("inspect"), {
                "runId": fork["runId"], "requestId": "recovery-design",
                "status": "not_submitted", "serviceId": "platform-service"})
            self.recover("inspect", expected=1, with_input=False)
            submit.assert_not_called()
            inspect.assert_not_called()
        self.assertEqual(self.recovery_path.read_bytes(), before)

    def test_recovery_rejects_partial_or_invalid_fork_rows_without_http_or_changes(self):
        self.prepare_recovery()
        row = json.loads(self.recovery_path.read_text(encoding="utf-8"))
        invalid = [
            {**row, "designRequestId": "recovery-design"},
            {**row, "designInput": self.recovery_context},
            {**row, "designRequestId": None},
            {**row, "designInput": None},
            {**row, "designRequestId": "", "designInput": {}},
            {key: value for key, value in row.items() if key != "forkedFrom"},
            {**row, "forkedFrom": "../other"},
            {**row, "forkedFrom": self.draft["runId"], "prompt": "不同来源需求"},
            {**row, "runId": "local-other"},
            {**row, "status": "succeeded"},
            {**row, "pendingOptimize": {"requestId": "pending"}},
            {**row, "elements": {**self.elements, "fields": " "}},
            {**row, "backend": {**row["backend"], "serviceId": "other"}},
        ]
        with patch.object(LocalClient, "submit") as submit, patch.object(LocalClient, "inspect") as inspect:
            for invalid_row in invalid:
                for action in ("inspect", "resume"):
                    with self.subTest(row=invalid_row, action=action):
                        self.recovery_path.write_text(json.dumps(invalid_row, indent=2), encoding="utf-8")
                        before = self.recovery_path.read_bytes()
                        self.recover(action, expected=1)
                        if action == "inspect":
                            self.recover(action, expected=1, with_input=False)
                        self.assertEqual(self.recovery_path.read_bytes(), before)
            submit.assert_not_called()
            inspect.assert_not_called()

    def test_recovery_requires_full_platform_context_and_supported_schema(self):
        self.prepare_recovery()
        before = self.recovery_path.read_bytes()
        context = self.recovery_context
        invalid = [
            {key: value for key, value in context.items() if key != missing}
            for missing in context
        ] + [[], {**context, "extra": True}, {**context, "runId": "local-other"},
             {**context, "elements": {**self.elements, "fields": "不同字段"}},
             {**context, "platform": "other"}, {**context, "sourceSignature": ""},
             {**context, "sourceSignature": None}, {**context, "intake": []}]
        with patch.object(LocalClient, "submit") as submit, patch.object(LocalClient, "inspect") as inspect:
            for changed in invalid:
                for action in ("inspect", "resume"):
                    with self.subTest(context=changed, action=action):
                        self.recover(action, expected=1, context=changed)
                        self.assertEqual(self.recovery_path.read_bytes(), before)
            self.recover("resume", expected=1, with_input=False)
            for capability in ({"platformDesignSchema": "wrong"}, {"platforms": []}, {"platforms": "feishu"}):
                with patch.dict(self.capability, capability):
                    for action in ("inspect", "resume"):
                        with self.subTest(capability=capability, action=action):
                            self.recover(action, expected=1)
                            self.assertEqual(self.recovery_path.read_bytes(), before)
            submit.assert_not_called()
            inspect.assert_not_called()

    def test_recovery_resume_first_submits_once_and_stale_evidence_never_reposts(self):
        fork = self.prepare_recovery()
        self.assertEqual(self.recover("inspect")["status"], "not_submitted")
        before_calls = len(self.calls)
        self.design_status = "queued"
        self.assertEqual(self.recover("resume")["status"], "queued")
        self.assertEqual(self.calls[before_calls:], [{"requestId": "recovery-design", "operation": "platform-design",
                                                     "input": self.recovery_context}])
        row = json.loads(self.recovery_path.read_text(encoding="utf-8"))
        self.assertEqual(row["designRequestId"], "recovery-design")
        self.assertEqual(row["designInput"], self.recovery_context)
        before = self.recovery_path.read_bytes()
        original_inspect = LocalClient.inspect
        with patch.object(LocalClient, "submit", side_effect=AssertionError("已绑定不重发")) as submit, \
                patch.object(LocalClient, "inspect", autospec=True, side_effect=original_inspect) as inspect:
            self.assertEqual(self.recover("resume")["status"], "queued")
            self.requests["recovery-design"]["status"] = "succeeded"
            self.assertEqual(self.recover("resume")["design"]["platform"], "feishu")
            self.assertEqual(self.recover("inspect")["runId"], fork["runId"])
            self.recover("inspect", with_input=False)
            self.assertEqual(inspect.call_count, 4)
            submit.assert_not_called()
        self.assertEqual(self.recovery_path.read_bytes(), before)
        self.assertEqual(len(self.calls), before_calls + 1)

    def test_recovery_bound_inspect_and_resume_reject_source_input_and_request_conflicts(self):
        self.prepare_recovery()
        self.recover("resume")
        before = self.recovery_path.read_bytes()
        with patch.object(LocalClient, "submit") as submit, patch.object(LocalClient, "inspect") as inspect:
            for action in ("inspect", "resume"):
                for key, value in (("sourceSignature", "different-source"), ("intake", {"source": "different"}),
                                   ("platform", "dingtalk"), ("elements", {**self.elements, "fields": "不同"})):
                    with self.subTest(action=action, key=key):
                        self.recover(action, expected=1, context={**self.recovery_context, key: value})
                self.recover(action, expected=1, command=[self.recovery_context["runId"], "--request-id", "other-design"])
            submit.assert_not_called()
            inspect.assert_not_called()
        self.assertEqual(self.recovery_path.read_bytes(), before)

    def test_recovery_bound_inspect_checks_context_even_for_original_nonfork_draft(self):
        self.submit_design()
        before = self.saved_row()
        context_path = self.path / "original-inspect.json"
        with patch.object(LocalClient, "inspect") as inspect, patch.object(LocalClient, "submit") as submit:
            for changed in ({**self.context, "sourceSignature": "wrong"}, {**self.context, "intake": {}},
                            {key: value for key, value in self.context.items() if key != "platform"}):
                context_path.write_text(json.dumps(changed), encoding="utf-8")
                self.run_cli(["design", "inspect", *self.command, "--input", str(context_path)], expected=1)
            inspect.assert_not_called()
            submit.assert_not_called()
        context_path.write_text(json.dumps(self.context), encoding="utf-8")
        self.assertEqual(self.run_cli(["design", "inspect", *self.command, "--input", str(context_path)])["status"], "succeeded")
        self.assertEqual(self.saved_row(), before)

    def test_recovery_timeout_keeps_binding_and_later_resume_only_inspects(self):
        self.prepare_recovery()
        original_submit = LocalClient.submit

        def submit_then_timeout(client, request_id, operation, data):
            result = original_submit(client, request_id, operation, data)
            self.assertEqual(result["status"], "succeeded")
            raise ApiError("LOCAL_REVIEW_REQUIRED", "提交后超时，状态未知")

        with patch.object(LocalClient, "submit", autospec=True, side_effect=submit_then_timeout) as submit:
            self.recover("resume", expected=1)
            self.assertEqual(submit.call_count, 1)
        before = self.recovery_path.read_bytes()
        row = json.loads(before)
        self.assertEqual(row["designInput"], self.recovery_context)
        self.assertEqual(row["designRequestId"], "recovery-design")
        original_inspect = LocalClient.inspect
        with patch.object(LocalClient, "submit", side_effect=AssertionError("超时后不重发")) as submit, \
                patch.object(LocalClient, "inspect", autospec=True, side_effect=original_inspect) as inspect:
            self.recover("resume")
            self.assertEqual(inspect.call_count, 1)
            submit.assert_not_called()
        self.assertEqual(self.recovery_path.read_bytes(), before)
        self.assertEqual(sum(call["requestId"] == "recovery-design" for call in self.calls), 1)

    def test_recovery_online_resume_rejected_before_connecting(self):
        with patch("basebuilder_cli.cli.BaseBuilderApiClient") as online, \
                patch("basebuilder_cli.local.dispatch") as dispatch, redirect_stdout(io.StringIO()) as out:
            try:
                code = main(["design", "resume", self.draft["runId"], "--request-id", "online-resume"])
            except SystemExit as error:
                self.fail(f"resume 应返回本地专属错误，实际 parser 退出 {error.code}")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "LOCAL_MODE_REQUIRED")
        online.assert_not_called()
        dispatch.assert_not_called()

    def test_recovery_cli_lock_refusal_does_not_damage_or_bind_fork(self):
        self.prepare_recovery()
        before = self.recovery_path.read_bytes()
        if os.name == "nt":
            target = "msvcrt.locking"
        else:
            target = "fcntl.flock"
        with patch(target, side_effect=OSError("already locked")) as lock, \
                patch("basebuilder_cli.local.dispatch_locked") as dispatch:
            self.recover("resume", expected=1)
            self.assertEqual(lock.call_count, 1)
            dispatch.assert_not_called()
        self.assertEqual(self.recovery_path.read_bytes(), before)
        self.assertEqual(self.recover("inspect")["status"], "not_submitted")

    def assert_design_error_inspections(self, expected):
        calls_before = list(self.calls)
        row_path = self.path / "runs" / (self.draft["runId"] + ".json")
        before = row_path.read_bytes()
        context_path = self.path / "error-inspect-context.json"
        context_path.write_text(json.dumps(self.context), encoding="utf-8")
        for command in (["design", "inspect", *self.command],
                        ["design", "inspect", *self.command, "--input", str(context_path)],
                        ["design", "resume", *self.command, "--input", str(context_path)],
                        ["runs", "inspect", self.draft["runId"]]):
            with self.subTest(command=command):
                result = self.run_cli(command)
                receipt = result["snapshot"] if command[0] == "runs" else result
                self.assertEqual(receipt["error"], expected)
                self.assertEqual(receipt["status"], self.requests["platform-design"]["status"])
                self.assertEqual(receipt["requestId"], "platform-design")
                self.assertEqual(receipt["serviceId"], "platform-service")
                if command[0] == "runs":
                    self.assertEqual(set(receipt), {"serviceId", "requestId", "operation", "status", "error"})
                    self.assertEqual(receipt["operation"], "platform-design")
                self.assertNotIn("design", result)
        self.assertEqual(self.calls, calls_before, "inspect/resume 不得 POST 或重试")
        self.assertEqual(row_path.read_bytes(), before, "查询不得改写原绑定")

    def test_failed_design_returns_safe_error_on_submit_and_read_only_inspections(self):
        self.design_status = "failed"
        self.design_error = {"code": "LOCAL_DESIGN_OUTPUT_INVALID", "stage": "contract",
                             "reason": "invalid_relation_endpoint", "paths": ["relations.0.toFieldId"]}
        result = self.submit_design()
        self.assertEqual(result["error"], self.design_error)
        self.assert_design_error_inspections(self.design_error)
        self.assertEqual(self.saved_row()["designInput"], self.context)
        self.assertEqual(self.saved_row()["designRequestId"], "platform-design")
        self.assertEqual(len(self.calls), 2)

    def test_relation_contract_reasons_survive_http_submit_and_read_only_inspections(self):
        self.design_status = "failed"
        reasons = ("relation_table_missing", "relation_field_missing", "relation_field_type",
                   "relation_endpoint_reused")
        for reason in reasons:
            with self.subTest(reason=reason):
                safe = {"code": "LOCAL_DESIGN_OUTPUT_INVALID", "stage": "contract", "reason": reason,
                        "paths": ["relations.0.toFieldId"]}
                self.design_error = {**safe, "message": "SECRET-MESSAGE"}
                self.assertEqual(self.submit_design()["error"], safe)
                self.assert_design_error_inspections(safe)
                for invalid in ({**safe, "reason": "relation_unknown_SECRET"},
                                {**safe, "stage": "platform"},
                                {**safe, "paths": ["relations.0.SECRET"]},
                                {**safe, "raw": "SECRET"}):
                    self.requests["platform-design"]["error"] = invalid
                    self.assert_design_error_inspections({"code": safe["code"]})
                self.requests["platform-design"]["error"] = self.design_error
        self.assertEqual(self.saved_row()["designInput"], self.context)
        self.assertEqual(self.saved_row()["designRequestId"], "platform-design")

    def test_execution_failure_diagnostics_survive_http_submit_and_read_only_inspections(self):
        self.design_status = "failed"
        safe = {"code": "LOCAL_DESIGN_EXECUTION_FAILED", "stage": "initialization", "reason": "connection"}
        self.design_error = {**safe, "message": "SECRET-MESSAGE"}
        self.assertEqual(self.submit_design()["error"], safe)
        for stage in ("initialization", "execution"):
            for reason in EXECUTION_REASONS:
                with self.subTest(stage=stage, reason=reason):
                    safe = {"code": "LOCAL_DESIGN_EXECUTION_FAILED", "stage": stage, "reason": reason}
                    self.requests["platform-design"]["error"] = {**safe, "message": "SECRET-MESSAGE"}
                    self.assert_design_error_inspections(safe)
        for extra in ({"paths": []}, {"paths": None}, {"raw": "SECRET-RAW"},
                      {"input": "SECRET-INPUT"}, {"ctx": "SECRET-CTX"}, {"extra": "SECRET-EXTRA"}):
            self.requests["platform-design"]["error"] = {**safe, **extra}
            self.assert_design_error_inspections({"code": "LOCAL_DESIGN_EXECUTION_FAILED"})
        self.assertEqual(len(self.calls), 2)

    def test_failed_legacy_system_design_also_returns_safe_error(self):
        del self.context["platform"]
        self.design_status = "failed"
        self.design_error = {"code": "LOCAL_DESIGN_EXECUTION_FAILED"}
        self.assertEqual(self.submit_design()["error"], self.design_error)
        self.assertEqual(self.calls[-1]["operation"], "design")
        calls_before = list(self.calls)
        self.assertEqual(self.run_cli(["design", "inspect", *self.command])["error"], self.design_error)
        snapshot = self.run_cli(["runs", "inspect", self.draft["runId"]])["snapshot"]
        self.assertEqual(snapshot["error"], self.design_error)
        self.assertEqual(self.calls, calls_before)

    def test_interrupted_design_always_requires_review_including_historical_receipts(self):
        self.design_status = "interrupted"
        self.design_error = {"code": "LOCAL_DESIGN_OUTPUT_INVALID", "stage": "json", "reason": "invalid_json"}
        review = {"code": "LOCAL_REVIEW_REQUIRED"}
        self.assertEqual(self.submit_design()["error"], review)
        self.assert_design_error_inspections(review)
        del self.requests["platform-design"]["error"]
        self.assert_design_error_inspections(review)

    def test_historical_failed_code_only_and_missing_errors_are_supported(self):
        self.design_status = "failed"
        review = {"code": "LOCAL_REVIEW_REQUIRED"}
        self.assertEqual(self.submit_design()["error"], review)
        self.assert_design_error_inspections(review)
        for code in ("LOCAL_DESIGN_OUTPUT_INVALID", "LOCAL_DESIGN_EXECUTION_FAILED",
                     "LOCAL_EXECUTION_FAILED", "LOCAL_REVIEW_REQUIRED"):
            with self.subTest(code=code):
                error = {"code": code}
                self.requests["platform-design"]["error"] = error
                self.assert_design_error_inspections(error)

    def test_output_invalid_allows_only_matching_stage_reason_pairs(self):
        self.design_status = "failed"
        self.submit_design()
        pairs = {
            "json": ("invalid_json", "duplicate_key", "non_finite_number"),
            "contract": ("invalid_contract", "invalid_id", "invalid_name", "duplicate_identifier",
                         "invalid_options", "required_relation", "invalid_display_field",
                         "invalid_relation_endpoint", "unbound_relation"),
            "platform": ("platform_mismatch", "unsupported_relation", "unsupported_primary",
                         "field_name_too_long", "platform_limit"),
        }
        for stage, reasons in pairs.items():
            for reason in reasons:
                with self.subTest(stage=stage, reason=reason):
                    error = {"code": "LOCAL_DESIGN_OUTPUT_INVALID", "stage": stage, "reason": reason}
                    self.requests["platform-design"]["error"] = error
                    self.assert_design_error_inspections(error)

    def test_error_paths_accept_only_bounded_contract_tokens_and_indices(self):
        self.design_status = "failed"
        self.submit_design()
        tokens = ("schema", "designId", "revision", "name", "tables", "relations", "warnings", "platform",
                  "id", "displayFieldId", "fields", "type", "required", "options", "fromTableId",
                  "fromFieldId", "toTableId", "toFieldId", "fromMany", "toMany")
        boundary = ".".join(["tables"] * 22 + ["schema"])  # exactly 160 characters
        self.assertEqual(len(boundary), 160)
        for paths in ([], [boundary], ["tables.0.fields.499.options", "relations.499.fromMany"],
                      ["tables"] * 5, *([token] for token in tokens)):
            with self.subTest(paths=paths):
                error = {"code": "LOCAL_DESIGN_OUTPUT_INVALID", "stage": "contract",
                         "reason": "invalid_contract", "paths": paths}
                self.requests["platform-design"]["error"] = error
                self.assert_design_error_inspections(error)

    def test_jobs_fixed_message_is_ignored_without_losing_safe_diagnostics(self):
        self.design_status = "failed"
        safe = {"code": "LOCAL_DESIGN_OUTPUT_INVALID", "stage": "contract",
                "reason": "invalid_relation_endpoint", "paths": ["relations.0.toFieldId"]}
        self.design_error = {**safe, "message": "设计输出未通过结构校验，请人工核对；不会自动重试"}
        self.assertEqual(self.submit_design()["error"], safe)
        self.assert_design_error_inspections(safe)
        for message in ("SECRET-MESSAGE", None, [], {"raw": "SECRET-MESSAGE"}):
            with self.subTest(message=message):
                self.requests["platform-design"]["error"] = {**safe, "message": message}
                self.assert_design_error_inspections(safe)
        for code, message in (
                ("LOCAL_DESIGN_EXECUTION_FAILED", "设计执行失败，请人工核对模型服务或执行环境；不会自动重试"),
                ("LOCAL_EXECUTION_FAILED", "请求执行失败，请人工核对；不会自动重试"),
                ("LOCAL_REVIEW_REQUIRED", "原设计请求失败或中断，请人工核对；不会自动重新调用模型")):
            with self.subTest(code=code):
                self.requests["platform-design"]["error"] = {"code": code, "message": message}
                self.assert_design_error_inspections({"code": code})

    def test_failed_design_snapshot_discards_untrusted_payloads(self):
        self.design_status = "failed"
        self.design_error = {"code": "LOCAL_DESIGN_OUTPUT_INVALID", "stage": "json", "reason": "invalid_json"}
        self.assertEqual(self.submit_design()["error"], self.design_error)
        self.requests["platform-design"].update(
            result={"runId": "local-other", "design": {"raw": "SECRET-RESULT"}},
            message="SECRET-MESSAGE", raw="SECRET-RAW", input={"token": "SECRET-INPUT"},
            ctx={"value": "SECRET-CTX"}, extra="SECRET-EXTRA")
        self.assert_design_error_inspections(self.design_error)

    def test_malicious_or_malformed_error_details_fall_back_to_known_code_only(self):
        self.design_status = "failed"
        code_only = {"code": "LOCAL_DESIGN_OUTPUT_INVALID"}
        valid = {**code_only, "stage": "json", "reason": "invalid_json"}
        self.design_error = {**valid, "message": "SECRET-MESSAGE", "raw": "SECRET-RAW",
                             "input": {"token": "SECRET-INPUT"}, "ctx": {"value": "SECRET-CTX"}}
        self.assertEqual(self.submit_design()["error"], code_only)
        invalid = [
            {**valid, "raw": "SECRET-RAW"},
            {**valid, "input": {"token": "SECRET-INPUT"}}, {**valid, "ctx": {"value": "SECRET-CTX"}},
            {**valid, "extra": "SECRET-EXTRA"}, {**valid, "stage": "SECRET-STAGE"},
            {**valid, "stage": "contract"}, {**valid, "stage": []}, {**valid, "stage": {}},
            {**valid, "reason": "SECRET-REASON"}, {**valid, "reason": []}, {**valid, "reason": {}},
            {**code_only, "stage": "json"}, {**code_only, "reason": "invalid_json"},
            *({**valid, "paths": paths} for paths in (
                "tables.0", None, {}, [None], [1], [{}], [[]], [""], ["tables"] * 6,
                ["tables."], [".tables"], ["tables..id"], ["tables[0].id"], ["tables.500.id"],
                ["tables.-1.id"], ["tables.00.id"], ["tables.01.id"], ["tables.1e2.id"], ["tables.０.id"],
                ["tables.١.id"], ["tables.999.id"], ["tables.1000.id"],
                ["tables.0.SECRET-FIELD"], ["tables.0.message"], ["raw"], ["input"], ["ctx"],
                ["tables.0\n"], ["tables.0/fields"], ["tables", "SECRET-PATH"],
                [".".join(["tables"] * 23 + ["id"])],
            )),
        ]
        for error in invalid:
            with self.subTest(error=error):
                self.requests["platform-design"]["error"] = error
                self.assert_design_error_inspections(code_only)
        for code in ("LOCAL_DESIGN_EXECUTION_FAILED", "LOCAL_EXECUTION_FAILED", "LOCAL_REVIEW_REQUIRED"):
            with self.subTest(code=code):
                self.requests["platform-design"]["error"] = {**valid, "code": code}
                self.assert_design_error_inspections({"code": code})
        for error in (None, [], "SECRET-ERROR", {}, {"code": []}, {"code": {}},
                      {"code": "SECRET-CODE", "stage": "json", "reason": "invalid_json"}):
            with self.subTest(error=error):
                self.requests["platform-design"]["error"] = error
                self.assert_design_error_inspections({"code": "LOCAL_REVIEW_REQUIRED"})

    def test_error_sanitization_does_not_bypass_service_request_operation_or_run_binding(self):
        self.design_status = "failed"
        self.submit_design()
        receipt = self.requests["platform-design"]
        before_calls = list(self.calls)
        for key, value in (("serviceId", "other-service"), ("requestId", "other-request"),
                           ("operation", "design")):
            with self.subTest(key=key), patch.dict(receipt, {key: value}):
                self.run_cli(["design", "inspect", *self.command], expected=1)
                self.run_cli(["runs", "inspect", self.draft["runId"]], expected=1)
        receipt["status"] = "succeeded"
        receipt["result"]["runId"] = "local-other"
        self.run_cli(["design", "inspect", *self.command], expected=1)
        self.run_cli(["runs", "inspect", self.draft["runId"]], expected=1)
        self.assertEqual(self.calls, before_calls)

    def test_platform_context_forwarded_and_inspects_restore_bound_operation(self):
        self.design_status = "queued"
        self.assertEqual(self.submit_design()["status"], "queued")
        self.assertEqual(self.calls[-1], {"requestId": "platform-design", "operation": "platform-design", "input": self.context})
        self.assertEqual(self.saved_row()["designInput"], self.context)
        self.requests["platform-design"]["status"] = "succeeded"
        designed = self.run_cli(["design", "inspect", *self.command])
        self.assertEqual(designed["design"], {"schema": "basebuilder.platform-design/v1", "platform": "feishu"})
        restored = self.run_cli(["runs", "inspect", self.draft["runId"]])
        self.assertEqual(restored["snapshot"]["operation"], "platform-design")
        self.assertEqual(len(self.calls), 2)

    def test_dingtalk_explicit_capability_submits_and_inspects_restore(self):
        self.capability["platforms"] = ["feishu", "dingtalk"]
        self.context["platform"] = self.receipt_platform = "dingtalk"
        self.design_status = "queued"
        self.assertEqual(self.submit_design()["status"], "queued")
        self.assertEqual(self.calls[-1], {"requestId": "platform-design", "operation": "platform-design", "input": self.context})
        self.assertEqual(self.saved_row()["designInput"], self.context)
        self.requests["platform-design"]["status"] = "succeeded"
        designed = self.run_cli(["design", "inspect", *self.command])
        self.assertEqual(designed["design"], {"schema": "basebuilder.platform-design/v1", "platform": "dingtalk"})
        restored = self.run_cli(["runs", "inspect", self.draft["runId"]])
        self.assertEqual(restored["designInput"], self.context)
        self.assertEqual(restored["snapshot"]["operation"], "platform-design")
        self.assertEqual(restored["snapshot"]["result"]["design"], designed["design"])
        self.assertEqual(len(self.calls), 2)

    def test_dingtalk_rejects_feishu_receipt_on_submit_and_inspects(self):
        self.capability["platforms"] = ["feishu", "dingtalk"]
        self.context["platform"] = "dingtalk"
        rejected = self.submit_design(expected=1)
        self.assertIn("平台设计结果与原请求的平台或合同不一致", rejected["error"]["message"])
        self.assertEqual(self.saved_row()["designInput"], self.context)
        self.run_cli(["design", "inspect", *self.command], expected=1)
        self.run_cli(["runs", "inspect", self.draft["runId"]], expected=1)
        self.assertEqual(len(self.calls), 2)

    def test_dingtalk_bound_request_cannot_switch_to_feishu(self):
        self.capability["platforms"] = ["feishu", "dingtalk"]
        self.context["platform"] = self.receipt_platform = "dingtalk"
        self.submit_design()
        original = self.saved_row()
        self.context["platform"] = "feishu"
        rejected = self.submit_design(expected=1)
        self.assertIn("原设计请求已绑定不同内容", rejected["error"]["message"])
        self.assertEqual(self.saved_row(), original)
        self.assertEqual(len(self.calls), 2)

    def test_bound_request_rejects_platform_or_input_change(self):
        self.submit_design()
        original = self.saved_row()
        self.capability["platforms"] = ["feishu", "dingtalk"]
        for changed in ({**self.context, "platform": "dingtalk"},
                        {key: value for key, value in self.context.items() if key != "platform"},
                        {**self.context, "sourceSignature": "changed"}):
            with self.subTest(context=changed):
                self.context = changed
                self.submit_design(expected=1)
                self.assertEqual(self.saved_row(), original)
                self.assertEqual(len(self.calls), 2)

    def test_success_receipt_rejects_wrong_platform_and_schema(self):
        for schema, platform in (("basebuilder.platform-design/v1", "dingtalk"),
                                 ("basebuilder.system-design/v1", "feishu"),
                                 ("basebuilder.platform-design/v1", None)):
            with self.subTest(schema=schema, platform=platform):
                self.receipt_schema, self.receipt_platform = schema, platform
                self.submit_design(expected=1)
                self.assertEqual(self.saved_row().get("designInput"), self.context)
                self.run_cli(["design", "inspect", *self.command], expected=1)
                self.run_cli(["runs", "inspect", self.draft["runId"]], expected=1)

    def test_inspects_reject_wrong_platform_after_valid_submission(self):
        self.submit_design()
        self.requests["platform-design"]["result"]["design"]["platform"] = "dingtalk"
        self.run_cli(["design", "inspect", *self.command], expected=1)
        self.run_cli(["runs", "inspect", self.draft["runId"]], expected=1)
        self.assertEqual(len(self.calls), 2)

    def test_unsupported_capability_never_submits_or_binds_and_doctor_still_works(self):
        original = self.saved_row()
        for capability, platform in (({}, "feishu"),
                                     ({"platformDesignSchema": "wrong", "platforms": ["feishu"]}, "feishu"),
                                     ({"platformDesignSchema": "basebuilder.platform-design/v1", "platforms": []}, "feishu"),
                                     ({"platformDesignSchema": "basebuilder.platform-design/v1", "platforms": "feishu"}, "feishu"),
                                     ({"platformDesignSchema": "basebuilder.platform-design/v1", "platforms": ["feishu"]}, "dingtalk")):
            with self.subTest(capability=capability, platform=platform):
                self.capability = {"designOnly": True, "schema": "basebuilder.system-design/v1", **capability}
                self.assertTrue(self.run_cli(["doctor"])["summary"]["usable"])
                self.context["platform"] = platform
                rejected = self.submit_design(expected=1)
                self.assertIn("平台", rejected["error"]["message"])
                self.assertEqual(self.saved_row(), original)
                self.assertEqual(len(self.calls), 1)

    def test_context_rejects_unknown_platform_and_extra_keys_without_binding(self):
        original = self.saved_row()
        for changed in ({**self.context, "platform": "other"}, {**self.context, "extra": True},
                        {**self.context, "platform": None}, {**self.context, "platform": ["feishu"]}):
            with self.subTest(context=changed):
                self.context = changed
                self.submit_design(expected=1)
                self.assertEqual(self.saved_row(), original)
                self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
