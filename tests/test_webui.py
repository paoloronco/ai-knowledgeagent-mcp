import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "knowledge-mcp"
sys.path.insert(0, str(ROOT / "mcp"))
import webui as app


class AdminBoundaryTest(unittest.TestCase):
    def test_source_and_policy_cannot_escape_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "notes").mkdir()
            with patch.object(app, "SOURCE", source):
                self.assertEqual(app.source_dir("notes"), source / "notes")
                with self.assertRaises(ValueError):
                    app.source_dir("../elsewhere")

        original = app.DEFAULT_POLICY.read_text(encoding="utf-8")
        app.validate_policy(original)
        with self.assertRaises(ValueError):
            app.validate_policy(original.replace("  - sample-folder\n", ""))
        with self.assertRaises(ValueError):
            app.validate_policy(original.replace("  - .pem\n", "  - .PEM\n"))

    def test_local_ui_requires_token_for_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            source = data / "source"
            source.mkdir()
            (data / "config.json").write_text(json.dumps({"mcp_enabled": False}), encoding="utf-8")
            with (
                patch.object(app, "DATA", data),
                patch.object(app, "CONFIG", data / "config.json"),
                patch.object(app, "POLICY", data / "index-policy.yaml"),
                patch.object(app, "SOURCE", source),
            ):
                controller = app.Controller()
                with patch.object(app, "controller", controller):
                    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        url = f"http://127.0.0.1:{server.server_port}"
                        with urllib.request.urlopen(url) as response:
                            self.assertIn(app.TOKEN, response.read().decode())
                        request = urllib.request.Request(url + "/api/config", data=b"{}", headers={"Content-Type": "application/json"})
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            urllib.request.urlopen(request)
                        self.assertEqual(denied.exception.code, 403)
                        request.add_header("X-Control-Token", app.TOKEN)
                        with urllib.request.urlopen(request) as response:
                            self.assertEqual(response.status, 200)
                    finally:
                        server.shutdown()
                        server.server_close()
                        controller.close()


if __name__ == "__main__":
    unittest.main()
