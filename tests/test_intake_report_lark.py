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
    def test_skill_description_describes_when_to_use_basebuilder(self):
        skill_text = (ROOT / "skills" / "basebuilder-cli" / "SKILL.md").read_text()
        description_line = next(line for line in skill_text.splitlines() if line.startswith("description: "))

        self.assertIn("Use when", description_line)
        self.assertIn("BaseBuilder", description_line)
        self.assertIn("business", description_line.lower())
        self.assertNotIn("agent needs to use BaseBuilder CLI", description_line)
        self.assertNotIn("log in", description_line.lower())

    def test_repo_install_docs_prompt_skill_install_and_cli_can_install_it(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("basebuilder skill install --target codex", readme)
        self.assertIn("basebuilder skill install --target agents", readme)

        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            target = Path(tmp) / "skills" / "basebuilder-cli"
            with contextlib.redirect_stdout(out):
                exit_code = cli.main(["skill", "install", "--path", str(target)])

            installed = target / "SKILL.md"
            self.assertEqual(exit_code, 0)
            self.assertTrue(installed.exists())
            self.assertIn("BaseBuilder CLI", installed.read_text())
            self.assertIn(str(target), out.getvalue())

            generated = Path(tmp) / "generated-skill"
            generated.mkdir()
            (generated / "SKILL.md").write_text("---\nname: basebuilder-base-abc123\n---\n# Generated\n")
            with mock.patch.dict(os.environ, {"HOME": tmp}):
                with contextlib.redirect_stdout(io.StringIO()):
                    generated_code = cli.main(["skill", "install", "--source", str(generated), "--target", "codex"])
            self.assertEqual(generated_code, 0)
            self.assertTrue((Path(tmp) / ".codex" / "skills" / "basebuilder-base-abc123" / "SKILL.md").exists())

    def test_create_input_json_uses_gui_template_fields_not_prompt_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.json"
            input_path.write_text(json.dumps({
                "mode": "text",
                "我想要构建": "客户成功续费跟进系统",
                "我是": "小型客户成功团队负责人",
                "痛点": ["续费风险靠人工记忆", "跟进动作分散在聊天记录"],
                "已有资料": "历史客户清单和续费记录",
                "希望输出": ["客户健康度视图", "高风险续费跟进表"],
            }, ensure_ascii=False))
            out = io.StringIO()

            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeAnalyzeClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main(["create", "--input", str(input_path), "--format", "json"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("【BaseBuilder CLI Intake】", FakeAnalyzeClient.last_prompt)
        payload = json.loads(FakeAnalyzeClient.last_prompt)
        self.assertEqual(payload["schemaVersion"], "basebuilder.intake.v1")
        self.assertEqual(payload["mode"], "text")
        self.assertEqual(payload["intakeTemplate"]["wantToBuild"], "客户成功续费跟进系统")
        self.assertEqual(payload["intakeTemplate"]["role"], "小型客户成功团队负责人")
        self.assertIn("续费风险靠人工记忆", payload["intakeTemplate"]["painPoints"])
        self.assertIn("客户健康度视图", payload["intakeTemplate"]["desiredOutputs"])

    def test_create_excel_mode_keeps_multiple_files_as_schema_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            renewal_path = Path(tmp) / "renewal.csv"
            renewal_path.write_text("客户名,续费日期,风险等级\nA公司,2026-07-01,高\n")
            tickets_path = Path(tmp) / "tickets.csv"
            tickets_path.write_text("工单号,客户名,处理状态\nT-1,A公司,处理中\n")
            out = io.StringIO()

            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with mock.patch.object(cli, "BaseBuilderApiClient", FakeAnalyzeClient):
                    with contextlib.redirect_stdout(out):
                        exit_code = cli.main([
                            "create",
                            "--mode",
                            "excel",
                            "--file",
                            str(renewal_path),
                            "--file",
                            str(tickets_path),
                            "--format",
                            "json",
                        ])

        self.assertEqual(exit_code, 0)
        payload = json.loads(FakeAnalyzeClient.last_prompt)
        self.assertEqual(payload["mode"], "excel")
        self.assertEqual(payload["sourceTruth"], "uploaded_spreadsheets")
        self.assertEqual([file["fileName"] for file in payload["files"]], ["renewal.csv", "tickets.csv"])
        self.assertTrue(all(file["sourceRole"] == "schema_source" for file in payload["files"]))
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertIn("续费日期", encoded)
        self.assertIn("处理状态", encoded)

    def test_create_excel_mode_requires_spreadsheet_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()

            with mock.patch.dict(os.environ, {"BB_HOME": tmp, "BB_API_BASE": "https://www.basebuilder.cn"}):
                with contextlib.redirect_stdout(out):
                    exit_code = cli.main(["create", "--mode", "excel", "--prompt", "复刻现有台账", "--format", "json"])

        payload = json.loads(out.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["error"]["code"], "INTAKE_EXCEL_FILE_REQUIRED")

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
