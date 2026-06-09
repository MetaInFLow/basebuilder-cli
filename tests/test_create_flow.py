import sys
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

    def test_create_reuses_analyze_message_id_for_build_start(self):
        api = MessageIdFakeApi()
        flow = CreateFlow(api)

        result = flow.run(prompt="做一个 CRM", decisions=["accept"])

        self.assertEqual(result.status, "building")
        self.assertEqual(api.message_id, 789)
        self.assertEqual(api.task_id, "task_crm")


if __name__ == "__main__":
    unittest.main()
