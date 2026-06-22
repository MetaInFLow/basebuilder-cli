import sys
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from basebuilder_cli.create_flow import CreateFlow, ThreeElements


class FakeApi:
    def __init__(self):
        self.calls = []

    def analyze(self, prompt):
        self.calls.append(("analyze", prompt))
        return {
            "messageId": 456,
            "taskId": "task_inventory",
            "elements": {
                "manage_what": "管理跨境电商 SKU 与库存",
                "workflow": "录入 SKU -> 同步库存 -> 预警补货",
                "fields": "SKU编码、仓库、库存、补货阈值",
            },
        }

    def optimize(self, elements, instruction, message_id=None, task_id=None):
        self.calls.append(("optimize", instruction, message_id, task_id))
        return {
            "messageId": message_id,
            "taskId": task_id,
            "elements": {
                "manage_what": elements.manage_what,
                "workflow": elements.workflow + " -> 复盘利润",
                "fields": elements.fields + "、利润",
            },
        }

    def start_build(self, elements, message_id=None, task_id=None):
        self.calls.append(("start_build", elements, message_id, task_id))
        return {"runId": "run_123", "messageId": 456, "taskId": task_id}


class MessageIdFakeApi:
    def __init__(self):
        self.message_id = None
        self.task_id = None

    def analyze(self, prompt):
        return {
            "messageId": 789,
            "taskId": "task_crm",
            "elements": {
                "manage_what": "管理客户线索",
                "workflow": "录入线索 -> 跟进 -> 成交",
                "fields": "客户名、阶段、责任人",
            },
        }

    def start_build(self, elements, message_id=None, task_id=None):
        self.message_id = message_id
        self.task_id = task_id
        return {"runId": "message_789", "messageId": message_id, "taskId": task_id}


class EmptyOptimizeFakeApi(FakeApi):
    def optimize(self, elements, instruction, message_id=None, task_id=None):
        self.calls.append(("optimize", instruction, message_id, task_id))
        return {
            "messageId": message_id,
            "taskId": task_id,
            "elements": {
                "manage_what": "",
                "workflow": "",
                "fields": "",
                "background_knowledge": "",
            },
        }


class IncompleteAnalyzeFakeApi(FakeApi):
    def analyze(self, prompt):
        self.calls.append(("analyze", prompt))
        return {
            "messageId": 654,
            "taskId": "task_streaming",
            "elements": {
                "manage_what": "管理开发项目",
                "workflow": "",
                "fields": "",
            },
        }


class CreateFlowTest(unittest.TestCase):
    def test_create_does_not_start_build_before_confirmation(self):
        api = FakeApi()
        flow = CreateFlow(api)

        result = flow.run(prompt="做一个跨境电商进销存", decisions=["show"])

        self.assertEqual(result.status, "needs_confirmation")
        self.assertEqual([call[0] for call in api.calls], ["analyze"])

    def test_create_can_optimize_edit_and_confirm(self):
        api = FakeApi()
        flow = CreateFlow(api)

        result = flow.run(
            prompt="做一个跨境电商进销存",
            decisions=[
                {"action": "optimize", "instruction": "加利润复盘"},
                {"action": "edit", "fields": "SKU编码、仓库、库存、补货阈值、利润、责任人"},
                {"action": "accept"},
            ],
        )

        self.assertEqual(result.status, "building")
        self.assertEqual(result.run["runId"], "run_123")
        self.assertEqual(result.task_id, "task_inventory")
        self.assertEqual([call[0] for call in api.calls], ["analyze", "optimize", "start_build"])
        self.assertEqual(api.calls[1][2], 456)
        self.assertEqual(api.calls[1][3], "task_inventory")
        self.assertEqual(api.calls[2][2], 456)
        self.assertEqual(api.calls[2][3], "task_inventory")

    def test_optimize_can_include_multiple_file_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / "renewal-notes.md"
            spec_path.write_text("续费痛点：历史备注分散，需要沉淀续费风险。")
            csv_path = Path(tmp) / "renewal.csv"
            csv_path.write_text("客户名,续费日期,风险等级\nA公司,2026-07-01,高\n")
            api = FakeApi()
            flow = CreateFlow(api)

            result = flow.run(
                prompt="做一个客户成功续费系统",
                decisions=[
                    {
                        "action": "optimize",
                        "instruction": "根据附件补充续费风险字段",
                        "files": [str(spec_path), str(csv_path)],
                    },
                ],
            )

        self.assertEqual(result.status, "needs_confirmation")
        refine_payload = json.loads(api.calls[1][1])
        self.assertEqual(refine_payload["schemaVersion"], "basebuilder.three_elements_refine.v1")
        self.assertEqual(refine_payload["instruction"], "根据附件补充续费风险字段")
        self.assertEqual([file["fileName"] for file in refine_payload["files"]], ["renewal-notes.md", "renewal.csv"])
        encoded = json.dumps(refine_payload, ensure_ascii=False)
        self.assertIn("续费痛点", encoded)
        self.assertIn("风险等级", encoded)

    def test_empty_optimize_response_preserves_previous_three_elements(self):
        api = EmptyOptimizeFakeApi()
        flow = CreateFlow(api)

        result = flow.run(
            prompt="做一个跨境电商进销存",
            decisions=[{"action": "optimize", "instruction": "补全流程"}],
        )

        self.assertEqual(result.status, "needs_confirmation")
        self.assertEqual(result.elements.manage_what, "管理跨境电商 SKU 与库存")
        self.assertEqual(result.elements.workflow, "录入 SKU -> 同步库存 -> 预警补货")
        self.assertEqual(result.elements.fields, "SKU编码、仓库、库存、补货阈值")

    def test_incomplete_analyze_result_stays_streaming_and_never_starts_build(self):
        api = IncompleteAnalyzeFakeApi()
        flow = CreateFlow(api)

        result = flow.run(prompt="做一个开发项目管理表", decisions=["accept"])

        self.assertEqual(result.status, "analyzing")
        self.assertEqual(result.message_id, 654)
        self.assertEqual(result.task_id, "task_streaming")
        self.assertEqual([call[0] for call in api.calls], ["analyze"])

    def test_create_reuses_analyze_message_id_for_build_start(self):
        api = MessageIdFakeApi()
        flow = CreateFlow(api)

        result = flow.run(prompt="做一个 CRM", decisions=["accept"])

        self.assertEqual(result.status, "building")
        self.assertEqual(api.message_id, 789)
        self.assertEqual(api.task_id, "task_crm")


if __name__ == "__main__":
    unittest.main()
