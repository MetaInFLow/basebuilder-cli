import io
import json
import os
import secrets
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from basebuilder_cli.client import ApiError
from basebuilder_cli.cli import main
from basebuilder_cli.local import LocalClient, origin_url


class LocalHttpTest(unittest.TestCase):
    def test_real_http_draft_optimize_design_and_restore(self):
        calls = []
        elements = {"manage_what": "客户", "workflow": "录入到跟进", "fields": "名称"}
        updated = {**elements, "fields": "名称和阶段"}
        requests = {}
        token = secrets.token_hex(32)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def reply(self, data):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "data": {"serviceId": "service-test", **data}}).encode())
            def do_GET(self):
                self.assert_auth()
                if self.path == "/api/local/capabilities":
                    self.reply({"designOnly": True, "schema": "basebuilder.system-design/v1"})
                else:
                    self.reply(requests[self.path.rsplit("/", 1)[1]])
            def assert_auth(self):
                if self.headers.get("Authorization") != "Bearer " + token:
                    raise AssertionError("未使用独立本地token")
            def do_POST(self):
                self.assert_auth()
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(body)
                operation = body["operation"]
                result = {"elements": elements if operation == "analyze" else updated} if operation != "design" else {"runId": body["input"]["runId"], "design": {"schema": "basebuilder.system-design/v1"}}
                response = {"requestId": body["requestId"], "operation": operation, "status": "succeeded", "result": result}
                requests[body["requestId"]] = response
                self.reply(response)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                (path / "token").write_text(token, encoding="utf-8")
                env = {"BB_LOCAL_HOME": directory, "BB_LOCAL_TOKEN_FILE": str(path / "token"), "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"}
                base = ["--local-dev", "--api-base", f"http://127.0.0.1:{server.server_port}"]
                def run(args):
                    with redirect_stdout(io.StringIO()) as out:
                        code = main(base + args)
                    self.assertEqual(code, 0, out.getvalue())
                    return json.loads(out.getvalue())["data"]
                with patch.dict(os.environ, env), patch("basebuilder_cli.cli.load_config", side_effect=AssertionError("不读取线上token")):
                    self.assertTrue(run(["doctor", "--format", "json"])["summary"]["usable"])
                    draft = run(["create", "--prompt", "客户管理", "--request-id", "analyze-1", "--format", "json"])
                    self.assertEqual(draft["elements"], elements)
                    run(["create", "--prompt", "客户管理", "--request-id", "analyze-1", "--format", "json"])
                    optimized = run(["create", "optimize", draft["runId"], "--instruction", "增加阶段", "--request-id", "optimize-1", "--format", "json"])
                    self.assertEqual(run(["create", "optimize", draft["runId"], "--instruction", "增加阶段", "--request-id", "optimize-1", "--format", "json"]), optimized)
                    self.assertEqual(optimized["elements"], updated)
                    context = {"runId": draft["runId"], "elements": updated, "intake": {}, "sourceSignature": "source"}
                    (path / "context.json").write_text(json.dumps(context), encoding="utf-8")
                    command = [draft["runId"], "--request-id", "design-1", "--format", "json"]
                    designed = run(["design", "draft", *command, "--input", str(path / "context.json")])
                    self.assertEqual(designed["status"], "succeeded")
                    self.assertEqual(run(["design", "inspect", *command]), designed)
                    self.assertEqual([call["operation"] for call in calls], ["analyze", "optimize", "design"])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_redirects_never_forward_credentials_or_submit_to_target(self):
        forwarded = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def handle_request(self):
                if self.path == "/target":
                    forwarded.append((self.command, dict(self.headers)))
                    self.send_response(200)
                else:
                    code, target = self.path.strip("/").split("/")
                    self.send_response(int(code))
                    self.send_header("Location", target_origin + "/target" if target == "other" else "/target")
                self.end_headers()
            do_GET = handle_request
            do_POST = handle_request
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        target = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        target_origin = f"http://127.0.0.1:{target.server_port}"
        threads = [threading.Thread(target=item.serve_forever) for item in (server, target)]
        for thread in threads:
            thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                token_file = Path(directory) / "token"
                token_file.write_text(secrets.token_hex(32), encoding="utf-8")
                with patch.dict(os.environ, {"BB_LOCAL_TOKEN_FILE": str(token_file)}):
                    client = LocalClient(f"http://127.0.0.1:{server.server_port}")
                    for code in (301, 302, 303, 307, 308):
                        for destination in ("same", "other"):
                            for method in ("GET", "POST"):
                                with self.subTest(code=code, destination=destination, method=method):
                                    with self.assertRaises(ApiError) as error:
                                        client.request(method, f"/{code}/{destination}", {} if method == "POST" else None)
                                    self.assertEqual(error.exception.code, "LOCAL_REVIEW_REQUIRED")
                    self.assertEqual(forwarded, [])
        finally:
            for item in (server, target):
                item.shutdown()
            for thread in threads:
                thread.join()
            for item in (server, target):
                item.server_close()

    def test_strict_origin_variants(self):
        for value in ["http://localhost:8999", "http://127.1:8999", "http://127.0.0.1:8999/", "http://user@127.0.0.1:8999", "http://127.0.0.1:8999?x=1", "http://127.0.0.1:65536"]:
            with self.subTest(value=value), self.assertRaises(Exception):
                origin_url(value)


if __name__ == "__main__":
    unittest.main()
