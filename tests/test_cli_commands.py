import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from basebuilder_cli import cli
from basebuilder_cli.client import ApiError, BaseBuilderApiClient, StreamEvent


class FakeCreateClient:
    def __init__(self, api_base, token=""):
        self.api_base = api_base
        self.token = token

    def analyze(self, prompt):
        return {
            "messageId": 123,
            "taskId": "task_sample",
            "elements": {
                "manage_what": "管理跨境电商 SKU 与库存",
                "workflow": "录入 SKU -> 同步库存 -> 预警补货",
                "fields": "SKU编码、仓库、库存、补货阈值",
            }
        }

    def start_build(self, elements, message_id=None, task_id=None):
        return {
            "runId": "message_123",
            "messageId": message_id,
            "taskId": task_id,
            "status": "started",
        }

    def attach_progress(self, run_id):
        return iter([
            StreamEvent("snapshot", {"status": "running", "progress": 30, "message": "创建数据表"}),
            StreamEvent("snapshot", {
                "status": "success",
                "progress": 100,
                "baseUrl": "https://metainflow.feishu.cn/base/sample",
                "artifactCounts": {"table": 2, "field": 5, "view": 3},
            }),
        ])


class FakeInteractiveClient:
    def __init__(self, api_base, token=""):
        self.calls = []

    def analyze(self, prompt):
        self.calls.append(("analyze", prompt))
        return {
            "messageId": 321,
            "taskId": "task_cli_321",
            "elements": {
                "manage_what": "管理客户线索",
                "workflow": "录入线索 -> 跟进",
                "fields": "客户名、阶段",
            },
        }

    def optimize(self, elements, instruction, message_id=None, task_id=None):
        self.calls.append(("optimize", instruction, message_id, task_id))
        return {
            "messageId": 321,
            "taskId": task_id,
            "elements": {
                "manage_what": elements.manage_what,
                "workflow": "录入线索 -> 跟进 -> 成交复盘",
                "fields": elements.fields,
            },
        }

    def start_build(self, elements, message_id=None, task_id=None):
        self.calls.append(("start_build", elements, message_id, task_id))
        return {"runId": "message_321", "messageId": message_id, "taskId": task_id, "status": "started"}

    def attach_progress(self, run_id):
        return iter([])


class FakeInspectClient:
    def __init__(self, api_base, token=""):
        self.api_base = api_base
        self.token = token

    def run_snapshot(self, run_id):
        return {
            "status": "success",
            "progress": 100,
            "baseUrl": "https://metainflow.feishu.cn/base/inspect",
        }


class FakeVerboseAttachClient:
    def __init__(self, api_base, token=""):
        self.api_base = api_base
        self.token = token

    def attach_progress(self, run_id):
        return iter([
            StreamEvent("snapshot", {
                "success": True,
                "code": 200,
                "message": "ok",
                "data": {
                    "status": "processing",
                    "current_step": "fast_build.design_views",
                    "last_success_step": "fast_build.insert_data",
                    "task_id": "task_verbose",
                    "problem_text": {"prompt": "internal prompt", "token": "secret"},
                    "answer_text": [
                        {"message": "old message", "event_seq": 41},
                        {
                            "message": "正在设计视图",
                            "event_seq": 42,
                            "delivery": {
                                "data": {
                                    "url": "https://metainflow.feishu.cn/base/verbose",
                                    "table_name": "客户线索 CRM",
                                }
                            },
                        },
                    ],
                    "snapshot_cursor": {"event_seq": 42, "artifact_version": 7, "action_seq": 9},
                },
            })
        ])


class FakeAgentClient:
    last_payload = None

    def __init__(self, api_base, token=""):
        self.api_base = api_base
        self.token = token

    def device_start(self, device_name, **kwargs):
        FakeAgentClient.last_payload = {"device_name": device_name, **kwargs}
        fingerprint_signals = kwargs.get("fingerprint_signals") or {}
        if "hostname" in fingerprint_signals or "username" in fingerprint_signals or "mac" in fingerprint_signals:
            raise AssertionError("raw fingerprint signal leaked to API payload")
        return {
            "device_code": "bbdc_agent",
            "user_code": "ABCD-EFGH",
            "verification_url": "https://www.basebuilder.cn/cli/approve?user_code=ABCD-EFGH",
            "verificationUrl": "https://www.basebuilder.cn/cli/approve?user_code=ABCD-EFGH",
            "loginUrl": "https://www.basebuilder.cn/login?redirect=%2Fcli%2Fapprove",
            "registerUrl": "https://www.basebuilder.cn/login?register=1&redirect=%2Fcli%2Fapprove",
            "rechargeUrl": "https://www.basebuilder.cn/account?tab=subscribe&source=cli_agent",
            "intent": kwargs.get("intent"),
            "clientKind": kwargs.get("client_kind"),
            "fingerprintHash": kwargs.get("fingerprint_hash"),
            "expires_at": 1780970900,
            "poll_interval": 5,
        }


class FakeAuthErrorClient:
    def __init__(self, api_base, token=""):
        self.api_base = api_base
        self.token = token

    def me(self):
        raise ApiError("AUTH_REVOKED", "登录已退出，请重新运行 `basebuilder login`。", retryable=False)


class FakeUrlopenResponse:
    def __init__(self, payload: str):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload.encode()


class CliCommandTest(unittest.TestCase):
    def test_default_api_base_is_production_www_basebuilder(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp}, clear=False):
                os.environ.pop("BB_API_BASE", None)
                with contextlib.redirect_stdout(out):
                    exit_code = cli.main(["health", "--format", "json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["data"]["api_base"], "https://www.basebuilder.cn")

    def test_help_and_ext_describe_document_production_api_contract(self):
        help_text = cli.build_parser().format_help()
        self.assertIn("https://www.basebuilder.cn", help_text)
        self.assertIn("HTTPS port 443", help_text)
        self.assertIn("127.*", help_text)

        payload = cli.describe_payload()
        self.assertEqual(payload["api"]["default_base_url"], "https://www.basebuilder.cn")
        self.assertEqual(payload["api"]["production_port"], 443)
        self.assertIn("127.0.0.1:8999", payload["api"]["local_dev_override"])
        self.assertIn("我想要构建", payload["intake"]["templateFields"])
        self.assertIn("multiple spreadsheet files", payload["intake"]["excel"])
        self.assertIn("agent register", payload["commands"])
        self.assertEqual(payload["api"]["agent_registration"]["production_base_url"], "https://www.basebuilder.cn")

    def test_create_ndjson_streams_progress_without_natural_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeCreateClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main([
                            "create",
                            "--prompt",
                            "做一个跨境电商进销存",
                            "--format",
                            "ndjson",
                            "--auto-accept",
                        ])

        self.assertEqual(exit_code, 0)
        lines = [line for line in out.getvalue().splitlines() if line.strip()]
        payloads = [json.loads(line) for line in lines]
        self.assertEqual([payload["operation"] for payload in payloads], [
            "builds.analyze",
            "builds.create",
            "runs.attach.progress",
            "runs.attach.progress",
        ])
        self.assertTrue(all(payload["ok"] is True for payload in payloads))
        self.assertEqual(payloads[-1]["data"]["progress"], 100)

    def test_create_human_mode_prints_three_elements_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeCreateClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main([
                            "create",
                            "--prompt",
                            "做一个跨境电商进销存",
                            "--auto-accept",
                        ])

        text = out.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("三要素:", text)
        self.assertIn("管理对象: 管理跨境电商 SKU 与库存", text)
        self.assertIn("snapshot 30%: 创建数据表", text)
        self.assertIn("https://metainflow.feishu.cn/base/sample", text)
        self.assertIn("summary tables=2 fields=5 views=3", text)

    def test_interactive_ndjson_create_supports_optimize_edit_accept_without_stdout_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            err = io.StringIO()
            inputs = iter([
                "客户线索 CRM",
                "销售运营",
                "",
                "线索分散",
                "",
                "线索表",
                "o",
                "加成交复盘",
                "",
                "e",
                "",
                "",
                "客户名、阶段、成交金额",
                "a",
            ])
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeInteractiveClient):
                    with mock.patch("sys.stdin.isatty", return_value=True):
                        with mock.patch("builtins.input", side_effect=lambda: next(inputs)):
                            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                                exit_code = cli.main(["create", "--format", "ndjson"])

        self.assertEqual(exit_code, 0)
        payloads = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
        self.assertEqual([payload["operation"] for payload in payloads], [
            "builds.analyze",
            "builds.optimize",
            "builds.edit",
            "builds.create",
        ])
        self.assertNotIn("请输入", out.getvalue())
        self.assertNotIn("确认", out.getvalue())
        self.assertIn("请输入", err.getvalue())
        self.assertEqual(payloads[-1]["data"]["runId"], "message_321")
        self.assertEqual(payloads[-1]["meta"]["messageId"], 321)
        self.assertEqual(payloads[-1]["meta"]["taskId"], "task_cli_321")

    def test_create_flow_preserves_task_id_through_optimize_edit_accept(self):
        client = FakeInteractiveClient("https://www.basebuilder.cn")
        flow = cli.CreateFlow(client)

        result = flow.run("做一个客户线索 CRM", [
            {"action": "optimize", "instruction": "加成交复盘"},
            {"action": "edit", "fields": "客户名、阶段、成交金额"},
            "accept",
        ])

        self.assertEqual(result.message_id, 321)
        self.assertEqual(result.task_id, "task_cli_321")
        self.assertEqual(client.calls[1], ("optimize", "加成交复盘", 321, "task_cli_321"))
        self.assertEqual(client.calls[2][0], "start_build")
        self.assertEqual(client.calls[2][2], 321)
        self.assertEqual(client.calls[2][3], "task_cli_321")

    def test_create_flow_does_not_start_build_before_confirmation(self):
        client = FakeInteractiveClient("https://www.basebuilder.cn")
        flow = cli.CreateFlow(client)

        result = flow.run("做一个客户线索 CRM", [
            "show",
            {"action": "edit", "fields": "客户名、阶段、成交金额"},
        ])

        self.assertEqual(result.status, "needs_confirmation")
        self.assertEqual(result.run, {})
        self.assertNotIn("start_build", [call[0] for call in client.calls])

    def test_runs_inspect_fetches_api_snapshot_when_token_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                cli.save_config(cli.CliConfig(api_base="https://www.basebuilder.cn", token="token_sample"))
                cli.save_run("message_123", {"run_id": "message_123", "status": "running"})
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeInspectClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["runs", "inspect", "message_123", "--format", "json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["data"]["snapshot"]["status"], "success")
        self.assertEqual(payload["data"]["snapshot"]["progress"], 100)

    def test_runs_attach_ndjson_compacts_verbose_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                cli.save_config(cli.CliConfig(api_base="https://www.basebuilder.cn", token="token_sample"))
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeVerboseAttachClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["runs", "attach", "message_123", "--format", "ndjson"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["data"]["status"], "processing")
        self.assertEqual(payload["data"]["currentStep"], "fast_build.design_views")
        self.assertEqual(payload["data"]["message"], "正在设计视图")
        self.assertEqual(payload["data"]["baseUrl"], "https://metainflow.feishu.cn/base/verbose")
        self.assertEqual(payload["data"]["cursor"]["event_seq"], 42)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("answer_text", encoded)
        self.assertNotIn("problem_text", encoded)
        self.assertNotIn("secret", encoded)

    def test_client_treats_legacy_success_false_response_as_api_error(self):
        client = BaseBuilderApiClient("https://www.basebuilder.cn")
        payload = json.dumps({"success": False, "code": 429, "message": "请勿频繁操作", "data": []})
        with mock.patch("urllib.request.urlopen", return_value=FakeUrlopenResponse(payload)):
            with self.assertRaises(ApiError) as raised:
                client.device_poll("device_code")

        self.assertEqual(raised.exception.code, "429")
        self.assertTrue(raised.exception.retryable)
        self.assertIn("频繁", str(raised.exception))

    def test_agent_register_json_returns_onboarding_urls_and_hash_only_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeAgentClient):
                    with mock.patch.object(cli.webbrowser, "open") as opened:
                        with contextlib.redirect_stdout(out):
                            exit_code = cli.main(["agent", "register", "--no-open", "--format", "json"])

        self.assertEqual(exit_code, 0)
        opened.assert_not_called()
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["operation"], "agents.register")
        self.assertEqual(payload["data"]["intent"], "agent_register")
        self.assertEqual(payload["data"]["verificationUrl"], "https://www.basebuilder.cn/cli/approve?user_code=ABCD-EFGH")
        self.assertEqual(payload["data"]["loginUrl"], "https://www.basebuilder.cn/login?redirect=%2Fcli%2Fapprove")
        self.assertEqual(payload["data"]["registerUrl"], "https://www.basebuilder.cn/login?register=1&redirect=%2Fcli%2Fapprove")
        self.assertEqual(payload["data"]["rechargeUrl"], "https://www.basebuilder.cn/account?tab=subscribe&source=cli_agent")
        self.assertTrue(str(payload["data"]["fingerprintHash"]).startswith("sha256:"))

        request_payload = FakeAgentClient.last_payload or {}
        self.assertEqual(request_payload["intent"], "agent_register")
        self.assertEqual(request_payload["client_kind"], "agent")
        self.assertTrue(str(request_payload["fingerprint_hash"]).startswith("sha256:"))
        encoded = json.dumps(request_payload, ensure_ascii=False).lower()
        self.assertNotIn('"hostname"', encoded)
        self.assertNotIn('"username"', encoded)
        self.assertNotIn('"mac"', encoded)

    def test_revoked_token_request_returns_structured_error_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                cli.save_config(cli.CliConfig(api_base="https://www.basebuilder.cn", token="revoked_token"))
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeAuthErrorClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["whoami", "--format", "json"])

        self.assertEqual(exit_code, 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["operation"], "me")
        self.assertEqual(payload["error"]["code"], "AUTH_REVOKED")
        self.assertEqual(payload["error"]["retryable"], False)


if __name__ == "__main__":
    unittest.main()
