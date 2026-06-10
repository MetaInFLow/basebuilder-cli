import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from basebuilder_cli.client import BaseBuilderApiClient
from basebuilder_cli.client import _is_terminal_snapshot
from basebuilder_cli.cli import compact_progress_data


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

    def test_finalize_delivery_overrides_stale_failed_design_flow_status(self):
        snapshot = {
            "ok": True,
            "operation": "runs.snapshot",
            "data": {
                "success": True,
                "code": 200,
                "message": "ok",
                "data": {
                    "status": "failed",
                    "current_step": "design_flow",
                    "last_success_step": "fast_build.finalize",
                    "snapshot": {
                        "feishu_url": "https://weave-ai.feishu.cn/base/sample",
                        "table_name": "客户健康度续费跟进系统",
                    },
                    "artifact_counts": {
                        "by_type": {"table": 3, "field": 47, "view": 12},
                        "total": 62,
                    },
                },
            },
        }

        compact = compact_progress_data(snapshot)

        self.assertEqual(compact["status"], "success")
        self.assertEqual(compact["currentStep"], "fast_build.finalize")
        self.assertEqual(compact["baseUrl"], "https://weave-ai.feishu.cn/base/sample")
        self.assertEqual(compact["artifactCounts"]["view"], 12)
        self.assertTrue(_is_terminal_snapshot(snapshot["data"]))

    def test_finalize_delivery_without_ok_envelope_overrides_stale_failed_status(self):
        snapshot = {
            "success": True,
            "data": {
                "status": "failed",
                "current_step": "design_flow",
                "last_success_step": "fast_build.finalize",
                "snapshot": {
                    "feishu_url": "https://weave-ai.feishu.cn/base/sample",
                    "table_name": "客户健康度续费跟进系统",
                },
                "artifact_counts": {
                    "by_type": {"table": 3, "field": 47, "view": 12},
                    "total": 62,
                },
            },
        }

        compact = compact_progress_data(snapshot)

        self.assertEqual(compact["status"], "success")
        self.assertEqual(compact["currentStep"], "fast_build.finalize")
        self.assertEqual(compact["baseUrl"], "https://weave-ai.feishu.cn/base/sample")
        self.assertEqual(compact["artifactCounts"]["view"], 12)
        self.assertTrue(_is_terminal_snapshot(snapshot))

    def test_processing_snapshot_with_finalized_nested_delivery_is_terminal(self):
        snapshot = {
            "status": "processing",
            "current_step": "design_flow",
            "last_success_step": "fast_build.finalize",
            "snapshot": {
                "feishu_url": "https://weave-ai.feishu.cn/base/sample",
                "table_name": "客户健康度续费跟进系统",
            },
        }

        compact = compact_progress_data(snapshot)

        self.assertEqual(compact["status"], "success")
        self.assertTrue(_is_terminal_snapshot(snapshot))


if __name__ == "__main__":
    unittest.main()
