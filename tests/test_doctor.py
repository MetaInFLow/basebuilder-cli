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
from basebuilder_cli.client import ApiError


class HealthyDoctorClient:
    def __init__(self, api_base, token=""):
        self.api_base = api_base
        self.token = token

    def capabilities(self):
        return {"version": "uat", "cli": {"enabled": True}}

    def me(self):
        return {
            "user": {"id": 700, "nickname": "Anthony"},
            "subscription": {"remaining_base_count": 3},
        }

    def run_snapshot(self, run_id):
        return {
            "status": "running",
            "progress": 47,
            "currentStep": "fast_build.refine_tables",
            "message": "正在优化表结构",
        }


class ZeroQuotaDoctorClient(HealthyDoctorClient):
    def me(self):
        return {
            "user": {"id": 700, "nickname": "Anthony"},
            "subscription": {"remaining_base_count": 0},
        }


class OfflineDoctorClient:
    def __init__(self, api_base, token=""):
        self.api_base = api_base
        self.token = token

    def capabilities(self):
        raise ApiError("NETWORK_ERROR", "无法连接 BaseBuilder API，请检查网络或 API 地址。", retryable=True)


class RevokedDoctorClient(HealthyDoctorClient):
    def me(self):
        raise ApiError("AUTH_REVOKED", "登录已退出，请重新运行 `basebuilder login`。", retryable=False)


class DoctorCommandTest(unittest.TestCase):
    def test_doctor_ready_reports_quota_and_running_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                cli.save_config(cli.CliConfig(api_base="https://www.basebuilder.cn", token="token_sample"))
                cli.save_run("message_700", {"run_id": "message_700", "status": "building"})
                with mock.patch.object(cli, "BaseBuilderApiClient", HealthyDoctorClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["doctor", "--format", "json"])

        payload = json.loads(out.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["operation"], "doctor")
        self.assertTrue(payload["data"]["summary"]["usable"])
        self.assertEqual(payload["data"]["summary"]["status"], "ready")
        self.assertEqual(payload["data"]["account"]["remainingCredits"], 3)
        self.assertEqual(payload["data"]["runs"]["running"][0]["runId"], "message_700")
        self.assertIn("basebuilder runs attach message_700", "\n".join(payload["data"]["summary"]["nextSteps"]))

    def test_doctor_without_token_tells_user_to_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", HealthyDoctorClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["doctor", "--format", "json"])

        payload = json.loads(out.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["data"]["summary"]["usable"])
        self.assertEqual(payload["data"]["summary"]["status"], "needs_login")
        self.assertIn("basebuilder login", "\n".join(payload["data"]["summary"]["nextSteps"]))

    def test_doctor_connection_failure_explains_network_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", OfflineDoctorClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["doctor", "--format", "json"])

        payload = json.loads(out.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["data"]["summary"]["usable"])
        self.assertEqual(payload["data"]["summary"]["status"], "offline")
        self.assertIn("NETWORK_ERROR", json.dumps(payload, ensure_ascii=False))
        self.assertIn("检查网络", "\n".join(payload["data"]["summary"]["nextSteps"]))

    def test_doctor_zero_quota_blocks_create_and_points_to_recharge(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                cli.save_config(cli.CliConfig(api_base="https://www.basebuilder.cn", token="token_sample"))
                with mock.patch.object(cli, "BaseBuilderApiClient", ZeroQuotaDoctorClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["doctor", "--format", "json"])

        payload = json.loads(out.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["data"]["summary"]["usable"])
        self.assertEqual(payload["data"]["summary"]["status"], "no_credits")
        self.assertEqual(payload["data"]["account"]["remainingCredits"], 0)
        self.assertIn("充值", "\n".join(payload["data"]["summary"]["nextSteps"]))

    def test_doctor_revoked_token_explains_relogin(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                cli.save_config(cli.CliConfig(api_base="https://www.basebuilder.cn", token="revoked_token"))
                with mock.patch.object(cli, "BaseBuilderApiClient", RevokedDoctorClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["doctor", "--format", "json"])

        payload = json.loads(out.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["data"]["summary"]["usable"])
        self.assertEqual(payload["data"]["summary"]["status"], "needs_login")
        self.assertIn("AUTH_REVOKED", json.dumps(payload, ensure_ascii=False))
        self.assertIn("basebuilder login", "\n".join(payload["data"]["summary"]["nextSteps"]))


if __name__ == "__main__":
    unittest.main()
