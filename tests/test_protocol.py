import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from basebuilder_cli.protocol import error_envelope, ok_envelope


class ProtocolTest(unittest.TestCase):
    def test_envelopes_are_stable(self):
        ok = ok_envelope("builds.create", {"runId": "run_1"}, {"messageId": 123})
        self.assertEqual(
            ok,
            {
                "ok": True,
                "operation": "builds.create",
                "data": {"runId": "run_1"},
                "meta": {"messageId": 123},
            },
        )

        err = error_envelope("builds.create", "AUTH_EXPIRED", "Login expired.", retryable=False)
        self.assertEqual(err["ok"], False)
        self.assertEqual(err["error"]["code"], "AUTH_EXPIRED")
        self.assertFalse(err["error"]["retryable"])

    def test_ext_describe_outputs_json_only(self):
        proc = subprocess.run(
            [sys.executable, "-m", "basebuilder_cli", "ext", "describe", "--format", "json"],
            cwd=ROOT,
            env={"PYTHONPATH": str(SRC)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["ok"], True)
        self.assertIn("create", payload["data"]["commands"])
        self.assertEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
