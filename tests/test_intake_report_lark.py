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


SAMPLE_ARTIFACT = {
    "base": {
        "name": "客户成功续费跟进系统",
        "url": "https://product.example/base/original",
        "appToken": "orig_base_token",
    },
    "summary": {"tables": 1, "fields": 2, "views": 1},
    "tables": [
        {
            "name": "客户账户",
            "tableId": "tbl_original",
            "fields": [
                {"name": "客户名", "type": "text", "fieldId": "fld_customer"},
                {"name": "续费风险", "type": "single_select", "fieldId": "fld_risk"},
            ],
            "views": [{"name": "高风险客户", "type": "grid", "viewId": "vew_risk"}],
        }
    ],
    "workflow": ["录入客户", "评估风险", "跟进续费"],
    "raw": {"token": "secret"},
}


class FakeAnalyzeClient:
    last_prompt = ""

    def __init__(self, api_base, token=""):
        self.api_base = api_base
        self.token = token

    def analyze(self, prompt):
        FakeAnalyzeClient.last_prompt = prompt
        return {
            "messageId": 901,
            "taskId": "task_intake",
            "elements": {
                "manage_what": "管理客户账户",
                "workflow": "录入客户 -> 跟进续费",
                "fields": "客户名、续费风险",
            },
        }

    def start_build(self, elements, message_id=None, task_id=None):
        raise AssertionError("build should not start before confirmation")


class IntakeReportLarkTest(unittest.TestCase):
    def test_create_input_json_builds_prompt_from_structured_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            input_path.write_text(json.dumps({
                "mode": "text",
                "title": "客户成功续费跟进系统",
                "scenario": "小型客户成功团队管理续费风险",
                "goals": ["统一客户健康度", "跟进高风险续费动作"],
                "constraints": ["不处理财务收款"],
            }, ensure_ascii=False))
            out = io.StringIO()

            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeAnalyzeClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["create", "--input", str(input_path), "--format", "json"])

        self.assertEqual(exit_code, 0)
        self.assertIn("客户成功续费跟进系统", FakeAnalyzeClient.last_prompt)
        self.assertIn("小型客户成功团队管理续费风险", FakeAnalyzeClient.last_prompt)
        self.assertIn("统一客户健康度", FakeAnalyzeClient.last_prompt)
        self.assertIn("不处理财务收款", FakeAnalyzeClient.last_prompt)

    def test_create_excel_csv_mode_sends_column_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "renewal.csv"
            csv_path.write_text("客户名,续费日期,风险等级\nA公司,2026-07-01,高\n")
            out = io.StringIO()

            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeAnalyzeClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main([
                            "create",
                            "--mode",
                            "excel",
                            "--file",
                            str(csv_path),
                            "--format",
                            "json",
                        ])

        self.assertEqual(exit_code, 0)
        self.assertIn("mode=excel", FakeAnalyzeClient.last_prompt)
        self.assertIn("source of truth", FakeAnalyzeClient.last_prompt)
        self.assertIn("客户名", FakeAnalyzeClient.last_prompt)
        self.assertIn("续费日期", FakeAnalyzeClient.last_prompt)
        self.assertIn("风险等级", FakeAnalyzeClient.last_prompt)

    def test_report_generate_and_render_from_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_md = Path(tmp) / "report.md"
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"BB_HOME": tmp}, clear=False):
                cli.save_run("message_901", {"run_id": "message_901", "artifact": SAMPLE_ARTIFACT})
                with contextlib.redirect_stdout(out):
                    generate_code = cli.main(["report", "generate", "message_901", "--out", str(report_path)])
                    render_code = cli.main(["report", "render", "message_901", "--report", str(report_path), "--out", str(report_md)])

            report = json.loads(report_path.read_text())
            self.assertEqual(generate_code, 0)
            self.assertEqual(render_code, 0)
            self.assertEqual(report["schemaVersion"], "basebuilder.report.v1")
            self.assertEqual(report["runId"], "message_901")
            self.assertEqual(report["base"]["url"], "https://product.example/base/original")
            self.assertNotIn("raw", json.dumps(report).lower())
            self.assertIn("客户成功续费跟进系统", report_md.read_text())

    def test_artifacts_skill_from_report_prefers_copied_base_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            skill_dir = Path(tmp) / "skill"
            report = {
                "schemaVersion": "basebuilder.report.v1",
                "runId": "message_901",
                **SAMPLE_ARTIFACT,
                "copy": {
                    "base": {
                        "url": "https://user.example/base/copied",
                        "appToken": "copied_base_token",
                    },
                    "tableIdMap": {"tbl_original": "tbl_copied"},
                    "fieldIdMap": {"fld_customer": "fld_customer_copied"},
                    "viewIdMap": {"vew_risk": "vew_risk_copied"},
                },
            }
            report_path.write_text(json.dumps(report, ensure_ascii=False))
            out = io.StringIO()

            with contextlib.redirect_stdout(out):
                exit_code = cli.main([
                    "artifacts",
                    "skill",
                    "message_901",
                    "--from-report",
                    str(report_path),
                    "--out",
                    str(skill_dir),
                ])

            skill_text = (skill_dir / "SKILL.md").read_text()
            schema = json.loads((skill_dir / "references" / "base-schema.json").read_text())
            self.assertEqual(exit_code, 0)
            self.assertIn("https://user.example/base/copied", skill_text)
            self.assertIn("copied_base_token", json.dumps(schema, ensure_ascii=False))
            self.assertIn("tbl_copied", json.dumps(schema, ensure_ascii=False))
            self.assertNotIn("https://product.example/base/original", skill_text)

    def test_lark_copy_merges_copy_result_into_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            copy_path = Path(tmp) / "copy-result.json"
            report_path.write_text(json.dumps({
                "schemaVersion": "basebuilder.report.v1",
                "runId": "message_901",
                **SAMPLE_ARTIFACT,
            }, ensure_ascii=False))
            copy_path.write_text(json.dumps({
                "base": {"url": "https://user.example/base/copied", "appToken": "copied_base_token"},
                "tableIdMap": {"tbl_original": "tbl_copied"},
            }, ensure_ascii=False))
            out = io.StringIO()

            with contextlib.redirect_stdout(out):
                exit_code = cli.main([
                    "lark",
                    "copy",
                    "message_901",
                    "--report",
                    str(report_path),
                    "--copy-result",
                    str(copy_path),
                ])

            report = json.loads(report_path.read_text())
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["copy"]["base"]["url"], "https://user.example/base/copied")
            self.assertEqual(report["copy"]["tableIdMap"]["tbl_original"], "tbl_copied")

    def test_lark_copy_without_tool_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report_path.write_text(json.dumps({"schemaVersion": "basebuilder.report.v1", "runId": "message_901"}, ensure_ascii=False))
            out = io.StringIO()

            with mock.patch("shutil.which", return_value=None):
                with contextlib.redirect_stdout(out):
                    exit_code = cli.main(["lark", "copy", "message_901", "--report", str(report_path)])

        payload = json.loads(out.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["error"]["code"], "LARKCLI_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
