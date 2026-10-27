import argparse
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
from basebuilder_cli.cli import main


class LocalModeTest(unittest.TestCase):
    def test_invalid_design_context_and_optimize_id_leave_draft_editable(self):
        from basebuilder_cli.local import save
        with tempfile.TemporaryDirectory() as directory:
            row = {"runId": "local-analyze", "backend": {"origin": "http://127.0.0.1:8999", "serviceId": "test"},
                   "elements": {"manage_what": "客户", "workflow": "跟进", "fields": "名称"}}
            path = Path(directory) / "runs/local-analyze.json"
            save(path, row)
            original = path.read_bytes()
            context = {"runId": row["runId"], "elements": row["elements"], "intake": {}, "sourceSignature": "source"}
            source = Path(directory) / "context.json"
            base = ["--local-dev", "--api-base", row["backend"]["origin"]]
            with patch.dict(os.environ, {"BB_LOCAL_HOME": directory}), patch("basebuilder_cli.local.LocalClient") as client:
                client.return_value.capabilities.return_value = {"serviceId": "test"}
                for invalid in ({"intake": []}, {"sourceSignature": ""}, {"sourceSignature": 1},
                                {"intake": {"brief": "中" * 50000}}, {"intake": {"invalid": float("nan")}}):
                    source.write_text(json.dumps({**context, **invalid}), encoding="utf-8")
                    with self.subTest(invalid=invalid), redirect_stdout(io.StringIO()):
                        self.assertEqual(main(base + ["design", "draft", row["runId"], "--request-id", "design-1", "--input", str(source)]), 1)
                    self.assertEqual(path.read_bytes(), original)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(base + ["create", "optimize", row["runId"], "--instruction", "增加阶段", "--request-id", "bad/id"]), 1)
                self.assertEqual(path.read_bytes(), original)
                client.return_value.submit.assert_not_called()
                source.write_text(json.dumps(context), encoding="utf-8")
                client.return_value.submit.return_value = {"status": "queued"}
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(base + ["design", "draft", row["runId"], "--request-id", "design-1", "--input", str(source)]), 0)
                client.return_value.submit.assert_called_once_with("design-1", "design", context)

    def test_pending_optimization_cannot_silently_switch_request_id(self):
        from basebuilder_cli.local import save
        with tempfile.TemporaryDirectory() as directory:
            row = {"runId": "local-analyze", "backend": {"origin": "http://127.0.0.1:8999", "serviceId": "test"},
                   "elements": {"manage_what": "客户", "workflow": "跟进", "fields": "名称"}}
            row["pendingOptimize"] = {"requestId": "original", "input": {"elements": row["elements"], "instruction": "增加阶段"}}
            path = Path(directory) / "runs/local-analyze.json"
            save(path, row)
            original = path.read_bytes()
            with patch.dict(os.environ, {"BB_LOCAL_HOME": directory}), patch("basebuilder_cli.local.LocalClient") as client:
                client.return_value.capabilities.return_value = {"serviceId": "test"}
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--local-dev", "--api-base", row["backend"]["origin"], "create", "optimize", row["runId"], "--instruction", "增加阶段", "--request-id", "different"]), 1)
                client.return_value.submit.assert_not_called()
                self.assertEqual(path.read_bytes(), original)

    def test_process_lock_rejects_concurrent_cli_then_releases(self):
        from basebuilder_cli.client import ApiError
        from basebuilder_cli.local import dispatch
        source = (
            "import argparse, sys\n"
            "from unittest.mock import patch\n"
            "from basebuilder_cli.local import dispatch\n"
            "def hold(args):\n"
            "    print('locked', flush=True)\n"
            "    sys.stdin.readline()\n"
            "    return 0\n"
            "with patch('basebuilder_cli.local.dispatch_locked', side_effect=hold):\n"
            "    dispatch(argparse.Namespace())\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}}
            env.update(BB_LOCAL_HOME=directory, HOME=directory, USERPROFILE=directory,
                       PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                       PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            child = subprocess.Popen([sys.executable, "-u", "-c", source], cwd=directory, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8")
            ready = queue.Queue()
            reader = threading.Thread(target=lambda: ready.put(child.stdout.readline()))
            reader.start()
            try:
                self.assertEqual(ready.get(timeout=15).strip(), "locked")
                with patch.dict(os.environ, {"BB_LOCAL_HOME": directory}), patch("basebuilder_cli.local.dispatch_locked") as execute:
                    with self.assertRaises(ApiError) as error:
                        dispatch(argparse.Namespace())
                    self.assertEqual(error.exception.code, "LOCAL_REVIEW_REQUIRED")
                    execute.assert_not_called()
            finally:
                child.stdin.write("release\n")
                child.stdin.flush()
                child.stdin.close()
                child.wait(timeout=15)
                reader.join(timeout=15)
                stderr = child.stderr.read()
                child.stdout.close()
                child.stderr.close()
            self.assertEqual(child.returncode, 0, stderr)
            with patch.dict(os.environ, {"BB_LOCAL_HOME": directory}), patch("basebuilder_cli.local.dispatch_locked", return_value=0) as execute:
                self.assertEqual(dispatch(argparse.Namespace()), 0)
                execute.assert_called_once()

    def test_never_reads_online_config(self):
        with patch("basebuilder_cli.cli.load_config", side_effect=AssertionError("不可读取线上配置")), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--local-dev", "--api-base", "http://127.0.0.1:8999", "login"]), 1)
        self.assertIn("LOCAL", out.getvalue())

    def test_rejects_non_loopback(self):
        with patch("basebuilder_cli.cli.load_config", side_effect=AssertionError("不可读取线上配置")), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--local-dev", "--api-base", "http://example.test", "doctor", "--format", "json"]), 1)
        self.assertIn("LOCAL", out.getvalue())


if __name__ == "__main__":
    unittest.main()
