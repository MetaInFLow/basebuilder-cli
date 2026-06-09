import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from basebuilder_cli.client import BaseBuilderApiClient


class PollingClient(BaseBuilderApiClient):
    def __init__(self, snapshots):
        super().__init__("https://www.basebuilder.cn")
        self.snapshots = list(snapshots)
        self.calls = 0

    def run_snapshot(self, run_id):
        self.calls += 1
        index = min(self.calls - 1, len(self.snapshots) - 1)
        return self.snapshots[index]


class ProgressTest(unittest.TestCase):
    def test_attach_progress_polls_until_terminal_snapshot(self):
        client = PollingClient([
            {"status": "running", "progress": 12, "message": "创建数据表"},
            {"status": "running", "progress": 55, "message": "设计视图"},
            {"status": "success", "progress": 100, "baseUrl": "https://metainflow.feishu.cn/base/sample"},
        ])

        events = list(client.attach_progress("message_123", poll_interval=0, max_polls=5))

        self.assertEqual(client.calls, 3)
        self.assertEqual([event.type for event in events], ["snapshot", "snapshot", "snapshot"])
        self.assertEqual([event.data["progress"] for event in events], [12, 55, 100])

    def test_attach_progress_stops_after_max_polls_for_nonterminal_run(self):
        client = PollingClient([
            {"status": "running", "progress": 12},
        ])

        events = list(client.attach_progress("message_123", poll_interval=0, max_polls=2))

        self.assertEqual(client.calls, 2)
        self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
