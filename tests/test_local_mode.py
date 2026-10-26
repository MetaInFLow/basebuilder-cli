import argparse
import io
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
