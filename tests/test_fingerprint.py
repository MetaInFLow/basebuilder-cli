import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from basebuilder_cli.fingerprint import build_fingerprint


class FingerprintTest(unittest.TestCase):
    def test_fingerprint_is_stable_and_hash_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            first = build_fingerprint(state_dir)
            second = build_fingerprint(state_dir)

        self.assertEqual(first["fingerprint_hash"], second["fingerprint_hash"])
        self.assertTrue(str(first["fingerprint_hash"]).startswith("sha256:"))
        self.assertEqual(first["fingerprint_signals"]["signalSchema"], "v1")
        self.assertIn("os", first["fingerprint_signals"])
        self.assertIn("arch", first["fingerprint_signals"])
        self.assertIn("cliVersion", first["fingerprint_signals"])

        encoded = json.dumps(first, ensure_ascii=False).lower()
        self.assertNotIn('"hostname"', encoded)
        self.assertNotIn('"username"', encoded)
        self.assertNotIn('"mac"', encoded)


if __name__ == "__main__":
    unittest.main()
