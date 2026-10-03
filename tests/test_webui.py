import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "knowledge-mcp"
sys.path.insert(0, str(ROOT / "mcp"))
import webui as app
sys.path.insert(0, str(ROOT))
import host_agent


class AdminBoundaryTest(unittest.TestCase):
    def test_saved_policy_recovers_required_directory_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            policy_file = data / "index-policy.yaml"
            old_policy = app.DEFAULT_POLICY.read_text(encoding="utf-8")
            for name in ("coverage", "cache", ".cache", "vendor", ".stversions", "sample-folder", "sample-folder", "sample-folder", "sample-folder"):
                old_policy = old_policy.replace(f"  - {name}\n", "")
            policy_file.write_text(old_policy, encoding="utf-8")
            with (
                patch.object(app, "DATA", data), patch.object(app, "SOURCE", data / "documents"),
                patch.object(app, "MANAGED_SOURCE", data / "documents"), patch.object(app, "HOST_SOURCE", data / "host-documents"),
                patch.object(app, "CONFIG", data / "config.json"), patch.object(app, "POLICY", policy_file),
                patch.object(app, "AGENT_MANIFEST", data / "agent-manifest.json"),
            ):
                controller = app.Controller()
                app.validate_policy(policy_file.read_text(encoding="utf-8"))
                controller.close()

    def test_setup_progress_is_persisted_and_requires_successful_initial_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            source = data / "documents"
            mounted = Path(tmp) / "mounted"
            mounted.mkdir()
            with (
                patch.object(app, "DATA", data), patch.object(app, "SOURCE", source),
                patch.object(app, "MANAGED_SOURCE", source), patch.object(app, "HOST_SOURCE", data / "host-documents"),
                patch.object(app, "CONFIG", data / "config.json"), patch.object(app, "POLICY", data / "index-policy.yaml"),
                patch.object(app, "AUTH", data / "auth.json"), patch.object(app, "AGENT_MANIFEST", data / "agent-manifest.json"),
            ):
                controller = app.Controller()
                self.assertEqual(controller.config["setup_step"], 0)
                controller.set_password("long-test-password")
                self.assertEqual(controller.config["setup_step"], 1)
                with self.assertRaisesRegex(ValueError, "previous setup step"):
                    controller.advance_setup(3)
                for step in range(2, 6):
                    self.assertEqual(controller.advance_setup(step)["setup_step"], step)
                with self.assertRaises(ValueError):
                    controller.advance_setup(6)
                controller.update({"source_mode": "container", "source_root": str(mounted), "folders": [""]})
                self.assertEqual(controller.config["setup_step"], 2)
                for step in range(3, 6):
                    controller.advance_setup(step)
                controller.complete_onboarding()
                controller._finish_index(Mock(wait=lambda: 1), False)
                self.assertEqual(controller.config["setup_step"], 5)
                controller._finish_index(Mock(wait=lambda: 0), True)
                self.assertEqual(controller.config["setup_step"], 5)
                controller._finish_index(Mock(wait=lambda: 0), False)
                self.assertEqual(controller.config["setup_step"], 6)
                controller.close()
                restored = app.Controller()
                self.assertEqual(restored.config["setup_step"], 6)
                restored.close()

    def test_managed_source_is_created_on_first_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            source = data / "documents"
            (data / "config.json").write_text(json.dumps({"mcp_enabled": False}), encoding="utf-8")
            with (
                patch.object(app, "DATA", data),
                patch.object(app, "MANAGED_SOURCE", source),
                patch.object(app, "HOST_SOURCE", data / "host-documents"),
                patch.object(app, "SOURCE", source),
                patch.object(app, "CONFIG", data / "config.json"),
                patch.object(app, "POLICY", data / "index-policy.yaml"),
            ):
                controller = app.Controller()
                self.assertTrue(source.is_dir())
                self.assertEqual(app.source_dir(""), source)
                controller.close()

    def test_legacy_subfolder_is_migrated_and_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            source = data / "documents"
            (source / "notes").mkdir(parents=True)
            (data / "config.json").write_text(json.dumps({"subfolder": "notes", "mcp_enabled": False}), encoding="utf-8")
            with (
                patch.object(app, "DATA", data), patch.object(app, "MANAGED_SOURCE", source),
                patch.object(app, "SOURCE", source), patch.object(app, "CONFIG", data / "config.json"),
                patch.object(app, "HOST_SOURCE", data / "host-documents"),
                patch.object(app, "POLICY", data / "index-policy.yaml"),
            ):
                controller = app.Controller()
                self.assertEqual(controller.config["folders"], ["notes"])
                self.assertEqual(controller.config["source_root"], str(source))
                self.assertEqual(json.loads((data / "config.json").read_text())["folders"], ["notes"])
                controller.close()

    def test_document_root_can_change_to_another_visible_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            original = data / "documents"
            mounted = Path(tmp) / "mounted" / "knowledge"
            (mounted / "notes").mkdir(parents=True)
            with (
                patch.object(app, "DATA", data), patch.object(app, "MANAGED_SOURCE", original),
                patch.object(app, "SOURCE", original), patch.object(app, "CONFIG", data / "config.json"),
                patch.object(app, "HOST_SOURCE", data / "host-documents"),
                patch.object(app, "POLICY", data / "index-policy.yaml"),
            ):
                controller = app.Controller()
                result = controller.update({"source_mode": "container", "source_root": str(mounted), "folders": ["notes"]})
                self.assertEqual(result["source_root"], str(mounted))
                self.assertEqual(result["folders"], ["notes"])
                self.assertEqual(controller._env()["KNOWLEDGE_ROOT"], str(mounted))
                self.assertEqual(json.loads(controller._env()["INDEX_SOURCE_PATHS"]), ["notes"])
                with self.assertRaisesRegex(ValueError, "Mount the host folder"):
                    controller.update({"source_mode": "container", "source_root": str(Path(tmp) / "not-mounted"), "folders": [""]})
                with self.assertRaisesRegex(ValueError, "Application data cannot be indexed"):
                    controller.update({"source_mode": "container", "source_root": str(data), "folders": [""]})
                controller.close()
                restored = app.Controller()
                self.assertEqual(restored.config["source_root"], str(mounted))
                restored.close()

    def test_source_and_policy_cannot_escape_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "notes").mkdir()
            with patch.object(app, "SOURCE", source):
                self.assertEqual(app.source_dir("notes"), source / "notes")
                self.assertEqual(app.source_dir(str(source)), source)
                self.assertEqual(app.normalize_folders([str(source), "notes"]), ["", "notes"])
                with self.assertRaises(ValueError):
                    app.source_dir("../elsewhere")
                with self.assertRaises(ValueError):
                    app.source_dir(str(source.parent))

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
                patch.object(app, "MANAGED_SOURCE", source),
                patch.object(app, "HOST_SOURCE", data / "host-documents"),
                patch.object(app, "AUTH", data / "auth.json"),
            ):
                controller = app.Controller()
                with patch.object(app, "controller", controller):
                    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        url = f"http://127.0.0.1:{server.server_port}"
                        with urllib.request.urlopen(url) as response:
                            page = response.read().decode()
                            self.assertIn(app.TOKEN, page)
                            self.assertIn('lang="en"', page)
                            self.assertNotIn('type="file"', page)
                        lan = urllib.request.Request(url, headers={"Host": "10.10.10.80:8080"})
                        with urllib.request.urlopen(lan) as response:
                            self.assertEqual(response.status, 200)
                        external = urllib.request.Request(url, headers={"Host": "untrusted.example:8080"})
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            urllib.request.urlopen(external)
                        self.assertEqual(denied.exception.code, 403)
                        request = urllib.request.Request(url + "/api/config", data=b"{}", headers={"Content-Type": "application/json"})
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            urllib.request.urlopen(request)
                        self.assertEqual(denied.exception.code, 403)
                        request.add_header("X-Control-Token", app.TOKEN)
                        request.add_header("Host", "10.10.10.80:8080")
                        with urllib.request.urlopen(request) as response:
                            self.assertEqual(response.status, 200)
                        upload = urllib.request.Request(url + "/api/upload?path=notes%2Fexample.md", data=b"Example document", headers={"X-Control-Token": app.TOKEN})
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            urllib.request.urlopen(upload)
                        self.assertEqual(denied.exception.code, 404)
                        self.assertFalse((source / "notes" / "example.md").exists())
                        (source / "notes").mkdir()
                        config = {"folders": [str(source / "notes")], "interval_hours": 2}
                        request = urllib.request.Request(url + "/api/config", data=json.dumps(config).encode(), headers={"Content-Type": "application/json", "X-Control-Token": app.TOKEN})
                        with urllib.request.urlopen(request) as response:
                            self.assertEqual(json.load(response)["folders"], ["notes"])
                        self.assertEqual(json.loads((data / "config.json").read_text())["folders"], ["notes"])
                        controller.config.update(onboarding_complete=False, setup_step=5)
                        controller._save()
                        policy_request = urllib.request.Request(
                            url + "/api/policy",
                            data=json.dumps({"content": app.DEFAULT_POLICY.read_text(encoding="utf-8")}).encode(),
                            headers={"Content-Type": "application/json", "X-Control-Token": app.TOKEN},
                        )
                        with urllib.request.urlopen(policy_request) as response:
                            self.assertEqual(response.status, 200)
                        self.assertEqual(controller.config["setup_step"], 3)
                        self.assertEqual(json.loads((data / "config.json").read_text())["setup_step"], 3)
                    finally:
                        server.shutdown()
                        server.server_close()
                        controller.close()

    def test_password_blocks_status_and_changes_until_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            source = data / "documents"
            source.mkdir()
            with (
                patch.object(app, "DATA", data), patch.object(app, "MANAGED_SOURCE", source),
                patch.object(app, "SOURCE", source), patch.object(app, "CONFIG", data / "config.json"),
                patch.object(app, "HOST_SOURCE", data / "host-documents"),
                patch.object(app, "AUTH", data / "auth.json"), patch.object(app, "POLICY", data / "index-policy.yaml"),
            ):
                controller = app.Controller()
                controller.set_password("long-test-password")
                with patch.object(app, "controller", controller):
                    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        url = f"http://127.0.0.1:{server.server_port}"
                        with urllib.request.urlopen(url) as response:
                            self.assertNotIn(app.TOKEN, response.read().decode())
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            urllib.request.urlopen(url + "/api/status")
                        self.assertEqual(denied.exception.code, 401)
                        try:
                            with urllib.request.urlopen(url + "/api/health") as health:
                                self.assertEqual(health.status, 200)
                        except urllib.error.HTTPError as unhealthy:
                            self.assertEqual(unhealthy.code, 503)
                        request = urllib.request.Request(url + "/api/login", data=json.dumps({"password": "long-test-password"}).encode(), headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(request) as response:
                            cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                        request = urllib.request.Request(url + "/api/status", headers={"Cookie": cookie})
                        with urllib.request.urlopen(request) as response:
                            self.assertEqual(response.status, 200)
                    finally:
                        server.shutdown()
                        server.server_close()
                        controller.close()

    def test_host_agent_syncs_changed_files_and_removes_deleted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = base / "data"
            mirror = data / "documents"
            host_mirror = data / "host-documents"
            host = base / "host"
            (host / "notes").mkdir(parents=True)
            (host / "notes" / "first.md").write_text("first version", encoding="utf-8")
            (host / "secrets").mkdir()
            (host / "secrets" / "private.md").write_text("private", encoding="utf-8")
            with (
                patch.object(app, "DATA", data), patch.object(app, "SOURCE", mirror),
                patch.object(app, "MANAGED_SOURCE", mirror), patch.object(app, "CONFIG", data / "config.json"),
                patch.object(app, "HOST_SOURCE", host_mirror),
                patch.object(app, "AUTH", data / "auth.json"), patch.object(app, "AGENT_AUTH", data / "agent-auth.json"),
                patch.object(app, "AGENT_MANIFEST", data / "agent-manifest.json"),
                patch.object(app, "POLICY", data / "index-policy.yaml"),
            ):
                controller = app.Controller()
                controller.set_password("strong-test-password")
                token = controller.agent_pair()["token"]
                controller.update({"source_mode": "host_agent", "host_root": str(host), "folders": [""]})
                with patch.object(app, "controller", controller):
                    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    try:
                        url = f"http://127.0.0.1:{server.server_port}"
                        task = host_agent.request(url, token, "/api/agent/task")
                        host_agent.sync(url, token, task)
                        self.assertEqual((host_mirror / "notes" / "first.md").read_text(), "first version")
                        self.assertFalse((host_mirror / "secrets" / "private.md").exists())
                        self.assertTrue(controller.status()["source_ready"])
                        (host / "notes" / "first.md").write_text("second version", encoding="utf-8")
                        host_agent.sync(url, token, task)
                        self.assertEqual((host_mirror / "notes" / "first.md").read_text(), "second version")
                        (host / "notes" / "first.md").unlink()
                        host_agent.sync(url, token, task)
                        self.assertFalse((host_mirror / "notes" / "first.md").exists())
                        (host / "old.md").write_text("old folder", encoding="utf-8")
                        host_agent.sync(url, token, task)
                        self.assertTrue((host_mirror / "old.md").exists())
                        another_host = base / "another-host"
                        another_host.mkdir()
                        (another_host / "second.md").write_text("another folder", encoding="utf-8")
                        controller.update({"source_mode": "host_agent", "host_root": str(another_host), "folders": [""]})
                        self.assertFalse(controller.status()["source_ready"])
                        host_agent.sync(url, token, host_agent.request(url, token, "/api/agent/task"))
                        self.assertEqual((host_mirror / "second.md").read_text(), "another folder")
                        self.assertFalse((host_mirror / "old.md").exists())
                        self.assertEqual(json.loads((data / "config.json").read_text())["host_root"], str(another_host))
                        host_agent.request(url, token, "/api/agent/error", {"revision": controller.config["sync_revision"], "error": "Folder unavailable"})
                        self.assertFalse(controller.status()["source_ready"])
                        self.assertIn("Folder unavailable", controller.status()["agent_error"])
                        host_agent.sync(url, token, host_agent.request(url, token, "/api/agent/task"))
                        self.assertTrue(controller.status()["source_ready"])
                        refresh_id = controller.request_agent_sync()["sync_request"]
                        self.assertLess(controller.status()["agent_sync_request_completed"], refresh_id)
                        host_agent.sync(url, token, host_agent.request(url, token, "/api/agent/task"))
                        self.assertEqual(controller.status()["agent_sync_request_completed"], refresh_id)
                        bad = urllib.request.Request(url + "/api/agent/plan", data=b"{}", headers={"X-Agent-Token": "wrong"})
                        with self.assertRaises(urllib.error.HTTPError) as denied:
                            urllib.request.urlopen(bad)
                        self.assertEqual(denied.exception.code, 403)
                    finally:
                        server.shutdown()
                        server.server_close()
                        controller.close()


if __name__ == "__main__":
    unittest.main()
