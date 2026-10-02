import ipaddress
import json
import math
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/data")
MANAGED_SOURCE = DATA / "documents"
SOURCE = Path(os.getenv("KNOWLEDGE_ROOT", str(MANAGED_SOURCE))).resolve()
CONFIG = DATA / "config.json"
POLICY = DATA / "index-policy.yaml"
DEFAULT_POLICY = ROOT / "mcp" / "index-policy.yaml"
HTML = Path(__file__).with_name("webui.html")
TOKEN = secrets.token_urlsafe(32)


def source_dir(subfolder):
    if not isinstance(subfolder, str) or "\\" in subfolder:
        raise ValueError("Invalid folder")
    path = (SOURCE / subfolder).resolve()
    if not path.is_relative_to(SOURCE) or not path.is_dir():
        raise ValueError("Choose an existing folder in the document library")
    return path


def validate_policy(content):
    policy = yaml.safe_load(content)
    default = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError("Policy must be a YAML object")
    for key in ("exclude_directories", "exclude_top_level", "exclude_extensions"):
        actual = policy.get(key)
        if not isinstance(actual, list) or not all(isinstance(x, str) for x in actual):
            raise ValueError(f"{key} must be a list")
        required = set(default[key]) if key == "exclude_extensions" else {x.casefold() for x in default[key]}
        present = set(actual) if key == "exclude_extensions" else {x.casefold() for x in actual}
        if not required <= present:
            raise ValueError(f"Do not remove the default exclusions from {key}")
    if not isinstance(policy.get("include_extensions"), list) or not all(isinstance(x, str) for x in policy["include_extensions"]):
        raise ValueError("include_extensions must be a list")
    if type(policy.get("max_file_size_mb")) not in (int, float) or not math.isfinite(policy["max_file_size_mb"]) or policy["max_file_size_mb"] <= 0:
        raise ValueError("max_file_size_mb must be a positive number")


class Controller:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        if SOURCE == MANAGED_SOURCE:
            SOURCE.mkdir(parents=True, exist_ok=True)
        if not POLICY.exists():
            shutil.copyfile(DEFAULT_POLICY, POLICY)
        self.lock = threading.RLock()
        self.config = {"subfolder": "", "interval_hours": 0, "mcp_enabled": True, "last_run_at": 0}
        if CONFIG.exists():
            self.config.update(json.loads(CONFIG.read_text(encoding="utf-8")))
        try:
            source_dir(self.config["subfolder"])
        except ValueError:
            self.config["subfolder"] = ""
            self._save()
        self.mcp = None
        self.ingest = None
        self.last_result = None
        if self.config["mcp_enabled"]:
            self._start_mcp()
        threading.Thread(target=self._schedule, daemon=True).start()

    def _save(self):
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.config), encoding="utf-8")
        tmp.replace(CONFIG)

    def _env(self):
        return {**os.environ, "KNOWLEDGE_ROOT": str(SOURCE / self.config["subfolder"]), "POLICY_FILE": str(POLICY)}

    def _start_mcp(self):
        if self.mcp and self.mcp.poll() is None:
            return
        with (DATA / "mcp.log").open("a", encoding="utf-8") as log:
            self.mcp = subprocess.Popen([sys.executable, "mcp/server.py"], cwd=ROOT, env=self._env(), stdout=log, stderr=subprocess.STDOUT)

    def _stop_mcp(self):
        if self.mcp and self.mcp.poll() is None:
            self.mcp.terminate()
            try:
                self.mcp.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.mcp.kill()
                self.mcp.wait()
        self.mcp = None

    def update(self, values):
        subfolder = values.get("subfolder", self.config["subfolder"])
        source_dir(subfolder)
        interval = values.get("interval_hours", self.config["interval_hours"])
        if type(interval) is not int or not 0 <= interval <= 720:
            raise ValueError("Interval must be between 0 and 720 hours")
        enabled = values.get("mcp_enabled", self.config["mcp_enabled"])
        if type(enabled) is not bool:
            raise ValueError("Invalid MCP state")
        with self.lock:
            root_changed = subfolder != self.config["subfolder"]
            interval_changed = interval != self.config["interval_hours"]
            self.config.update(subfolder=subfolder, interval_hours=interval, mcp_enabled=enabled)
            if interval_changed:
                self.config["last_run_at"] = time.time()
            self._save()
            if not enabled or root_changed:
                self._stop_mcp()
            if enabled:
                self._start_mcp()
            return dict(self.config)

    def run_index(self, dry_run=False):
        with self.lock:
            if self.ingest and self.ingest.poll() is None:
                raise ValueError("Indexing is already running")
            source_dir(self.config["subfolder"])
            args = [sys.executable, "ingestion/ingest.py"]
            if dry_run:
                args += ["--dry-run", "--limit", "10"]
            with (DATA / "ingest.log").open("w", encoding="utf-8") as log:
                self.ingest = subprocess.Popen(args, cwd=ROOT, env=self._env(), stdout=log, stderr=subprocess.STDOUT)
            if not dry_run:
                self.config["last_run_at"] = time.time()
                self._save()
            threading.Thread(target=self._finish_index, args=(self.ingest, dry_run), daemon=True).start()

    def upload_file(self, relative_path, length, stream):
        if SOURCE != MANAGED_SOURCE:
            raise ValueError("Uploads are unavailable for a mounted document folder")
        if not isinstance(relative_path, str) or not 0 < len(relative_path) <= 1024 or "\\" in relative_path or any(ord(char) < 32 for char in relative_path):
            raise ValueError("Invalid file path")
        parts = relative_path.split("/")
        if any(part in ("", ".", "..") for part in parts) or PurePosixPath(relative_path).is_absolute():
            raise ValueError("Invalid file path")
        policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
        excluded_top = {name.casefold() for name in policy["exclude_top_level"]}
        excluded_dirs = {name.casefold() for name in policy["exclude_directories"]}
        extension = Path(parts[-1]).suffix.lower()
        if parts[0].casefold() in excluded_top or any(part.casefold() in excluded_dirs for part in parts[:-1]):
            raise ValueError("This folder is excluded by the indexing policy")
        if extension not in policy["include_extensions"] or extension in policy["exclude_extensions"]:
            raise ValueError("This file type is excluded by the indexing policy")
        if not 0 < length <= policy["max_file_size_mb"] * 1024 * 1024:
            raise ValueError("File is empty or exceeds the policy size limit")
        target = SOURCE.joinpath(*parts)
        if not target.resolve().is_relative_to(SOURCE):
            raise ValueError("Invalid file path")
        with self.lock:
            if self.ingest and self.ingest.poll() is None:
                raise ValueError("Wait until indexing finishes before uploading files")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                    temporary = Path(output.name)
                    remaining = length
                    while remaining:
                        chunk = stream.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Upload ended before the complete file arrived")
                        output.write(chunk)
                        remaining -= len(chunk)
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return {"saved": relative_path}

    def _finish_index(self, process, dry_run):
        code = process.wait()
        with self.lock:
            self.last_result = {"exit_code": code, "dry_run": dry_run, "finished_at": time.time()}
            if code == 0 and not dry_run and self.config["mcp_enabled"]:
                self._stop_mcp()
                self._start_mcp()

    def _schedule(self):
        while True:
            time.sleep(30)
            with self.lock:
                if self.config["mcp_enabled"]:
                    self._start_mcp()
                hours = self.config["interval_hours"]
                due = hours and time.time() - self.config["last_run_at"] >= hours * 3600
                running = self.ingest and self.ingest.poll() is None
            if due and not running:
                try:
                    self.run_index()
                except (OSError, ValueError):
                    pass

    def status(self):
        try:
            with urllib.request.urlopen(os.getenv("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/") + "/readyz", timeout=2) as response:
                qdrant = response.status == 200
        except Exception:
            qdrant = False
        with self.lock:
            log = DATA / "ingest.log"
            tail = ""
            if log.exists():
                with log.open("rb") as output:
                    output.seek(0, 2)
                    output.seek(max(0, output.tell() - 12000))
                    tail = output.read().decode("utf-8", errors="replace")
            return {
                "config": dict(self.config),
                "qdrant_ready": qdrant,
                "mcp_running": bool(self.mcp and self.mcp.poll() is None),
                "index_running": bool(self.ingest and self.ingest.poll() is None),
                "source_ready": SOURCE.is_dir(),
                "upload_enabled": SOURCE == MANAGED_SOURCE,
                "last_result": self.last_result,
                "log": tail,
            }

    def close(self):
        with self.lock:
            self._stop_mcp()
            if self.ingest and self.ingest.poll() is None:
                self.ingest.terminate()


controller = None


class Handler(BaseHTTPRequestHandler):
    def _allowed_host(self):
        try:
            host = urlsplit("//" + self.headers.get("Host", "")).hostname
            if host == "localhost":
                return True
            ipaddress.ip_address(host)
            return True
        except (ValueError, TypeError):
            return False

    def send(self, code, data, kind="application/json; charset=utf-8"):
        payload = data.encode("utf-8") if isinstance(data, str) else data
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self._allowed_host():
            self.send(403, json.dumps({"error": "Host not allowed"}))
            return
        if self.path == "/":
            self.send(200, HTML.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self.send(200, json.dumps(controller.status()))
        elif self.path == "/api/policy":
            self.send(200, json.dumps({"content": POLICY.read_text(encoding="utf-8")}))
        else:
            self.send(404, json.dumps({"error": "Not found"}))

    def do_POST(self):
        if not self._allowed_host() or self.headers.get("X-Control-Token") != TOKEN:
            self.send(403, json.dumps({"error": "Unauthorized request"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            route = urlsplit(self.path)
            if route.path == "/api/upload":
                paths = parse_qs(route.query).get("path", [])
                if len(paths) != 1:
                    raise ValueError("Provide one relative file path")
                self.send(200, json.dumps(controller.upload_file(paths[0], length, self.rfile)))
                return
            if not 0 < length <= 65536:
                raise ValueError("Request is too large or empty")
            values = json.loads(self.rfile.read(length))
            if not isinstance(values, dict):
                raise ValueError("Invalid data")
            if self.path == "/api/config":
                result = controller.update(values)
            elif self.path == "/api/index":
                controller.run_index(values.get("dry_run") is True)
                result = {"started": True}
            elif self.path == "/api/policy":
                content = values.get("content")
                if not isinstance(content, str):
                    raise ValueError("Invalid policy")
                validate_policy(content)
                tmp = POLICY.with_suffix(".tmp")
                tmp.write_text(content, encoding="utf-8")
                tmp.replace(POLICY)
                result = {"saved": True}
            else:
                self.send(404, json.dumps({"error": "Not found"}))
                return
            self.send(200, json.dumps(result))
        except (ValueError, yaml.YAMLError) as exc:
            self.send(400, json.dumps({"error": str(exc)}))
        except Exception:
            self.send(500, json.dumps({"error": "Internal error; check the container logs"}))
            raise


def main():
    global controller
    controller = Controller()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        controller.close()
        server.server_close()


if __name__ == "__main__":
    main()
