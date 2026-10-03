import ipaddress
import hashlib
import hmac
import json
import math
import os
import secrets
import shutil
import signal
import socket
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
AUTH = DATA / "auth.json"
POLICY = DATA / "index-policy.yaml"
DEFAULT_POLICY = ROOT / "mcp" / "index-policy.yaml"
HTML = Path(__file__).with_name("webui.html")
SCRIPT = Path(__file__).with_name("app.js")
TOKEN = secrets.token_urlsafe(32)


def source_dir(subfolder):
    if not isinstance(subfolder, str) or (os.name != "nt" and "\\" in subfolder):
        raise ValueError("Invalid folder")
    path = Path(subfolder)
    path = (path if path.is_absolute() else SOURCE / path).resolve()
    if not path.is_relative_to(SOURCE) or not path.is_dir():
        raise ValueError(f"Choose an existing folder inside {SOURCE}")
    return path


def normalize_folders(values):
    if not isinstance(values, list) or not values or len(values) > 32:
        raise ValueError("Choose between 1 and 32 folders")
    folders = []
    for value in values:
        path = source_dir(value)
        relative = path.relative_to(SOURCE).as_posix()
        if relative == ".":
            relative = ""
        if relative not in folders:
            folders.append(relative)
    return folders


def source_dir_or_false(value):
    try:
        source_dir(value)
        return True
    except ValueError:
        return False


def password_record(password):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValueError("Password must be at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600000)
    return {"salt": salt.hex(), "hash": digest.hex()}


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
    if not isinstance(policy.get("exclude_files", []), list) or not all(isinstance(x, str) and x and "\\" not in x and ".." not in Path(x).parts and not x.startswith("/") for x in policy.get("exclude_files", [])):
        raise ValueError("exclude_files must contain basenames or relative paths")
    supported = {".pdf", ".docx", ".pptx", ".md", ".txt", ".html", ".htm"}
    if not policy["include_extensions"] or any(x not in supported for x in policy["include_extensions"]):
        raise ValueError("include_extensions must use supported extensions")
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
        first_start = not CONFIG.exists()
        self.config = {"folders": [""], "interval_hours": 0, "mcp_enabled": False, "qdrant_enabled": True, "last_run_at": 0, "onboarding_complete": not first_start}
        migrated = False
        if CONFIG.exists():
            stored = json.loads(CONFIG.read_text(encoding="utf-8"))
            self.config.update(stored)
            migrated = "folders" not in stored
            if migrated:
                self.config["folders"] = [stored.get("subfolder", "")]
        try:
            self.config["folders"] = normalize_folders(self.config.get("folders", [self.config.get("subfolder", "")]))
        except ValueError:
            self.config["folders"] = [""]
            self._save()
        self.config.pop("subfolder", None)
        if migrated:
            self._save()
        self.sessions = {}
        self.login_attempts = {}
        self.stopping = False
        self.qdrant = None
        self.mcp = None
        self.ingest = None
        result_file = DATA / "last-result.json"
        self.last_result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else None
        if Path("/qdrant/qdrant").exists() and self.config["qdrant_enabled"]:
            self._start_qdrant()
        if self.config["mcp_enabled"] and (not Path("/qdrant/qdrant").exists() or self.config["qdrant_enabled"]):
            self._start_mcp()
        threading.Thread(target=self._schedule, daemon=True).start()

    def _save(self):
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.config), encoding="utf-8")
        tmp.replace(CONFIG)

    def password_enabled(self):
        return AUTH.exists()

    def set_password(self, password):
        record = password_record(password)
        with self.lock:
            tmp = AUTH.with_suffix(".tmp")
            tmp.write_text(json.dumps(record), encoding="utf-8")
            tmp.replace(AUTH)
            if os.name == "posix":
                AUTH.chmod(0o600)
            self.sessions.clear()

    def check_password(self, password):
        if not isinstance(password, str) or not AUTH.exists():
            return False
        record = json.loads(AUTH.read_text(encoding="utf-8"))
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(record["salt"]), 600000)
        return hmac.compare_digest(digest, bytes.fromhex(record["hash"]))

    def complete_onboarding(self):
        with self.lock:
            self.config["onboarding_complete"] = True
            self._save()

    def invalidate_result(self):
        with self.lock:
            self.last_result = None
            (DATA / "last-result.json").unlink(missing_ok=True)

    def _env(self):
        return {**os.environ, "KNOWLEDGE_ROOT": str(SOURCE), "INDEX_SOURCE_PATHS": json.dumps(self.config["folders"]), "POLICY_FILE": str(POLICY)}

    def _start_qdrant(self):
        if self.qdrant and self.qdrant.poll() is None:
            return
        self.qdrant = subprocess.Popen(["/qdrant/qdrant"], cwd="/qdrant", env=os.environ.copy())

    def _stop_qdrant(self):
        if self.qdrant and self.qdrant.poll() is None:
            self.qdrant.terminate()
            try:
                self.qdrant.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.qdrant.kill()
                self.qdrant.wait()
        self.qdrant = None

    def service(self, name, action):
        if name not in ("qdrant", "mcp") or action not in ("start", "stop", "restart"):
            raise ValueError("Invalid service action")
        with self.lock:
            if name == "qdrant":
                if not Path("/qdrant/qdrant").exists():
                    raise ValueError("Qdrant is managed externally in this installation")
                if self.ingest and self.ingest.poll() is None:
                    raise ValueError("Wait until indexing finishes")
                self.config["qdrant_enabled"] = action != "stop"
                self._save()
                if action in ("stop", "restart"):
                    self._stop_mcp()
                    self._stop_qdrant()
                if action in ("start", "restart"):
                    self._start_qdrant()
                    if self.config["mcp_enabled"]:
                        self._start_mcp()
            else:
                if action in ("start", "restart") and self.ingest and self.ingest.poll() is None:
                    raise ValueError("Wait until indexing finishes before starting MCP")
                if action in ("stop", "restart"):
                    self._stop_mcp()
                self.config["mcp_enabled"] = action != "stop"
                self._save()
                if action in ("start", "restart"):
                    self._start_mcp()
        return {"ok": True}

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
        folders = normalize_folders(values.get("folders", [values["subfolder"]] if "subfolder" in values else self.config["folders"]))
        interval = values.get("interval_hours", self.config["interval_hours"])
        if type(interval) is not int or not 0 <= interval <= 720:
            raise ValueError("Interval must be between 0 and 720 hours")
        enabled = values.get("mcp_enabled", self.config["mcp_enabled"])
        if type(enabled) is not bool:
            raise ValueError("Invalid MCP state")
        with self.lock:
            root_changed = folders != self.config["folders"]
            interval_changed = interval != self.config["interval_hours"]
            if root_changed and self.ingest and self.ingest.poll() is None:
                raise ValueError("Wait until indexing finishes before changing folders")
            self.config.update(folders=folders, interval_hours=interval, mcp_enabled=enabled)
            if root_changed:
                self.invalidate_result()
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
            normalize_folders(self.config["folders"])
            self.invalidate_result()
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
        excluded_files = {name.casefold() for name in policy.get("exclude_files", [])}
        extension = Path(parts[-1]).suffix.lower()
        if parts[0].casefold() in excluded_top or any(part.casefold() in excluded_dirs for part in parts[:-1]):
            raise ValueError("This folder is excluded by the indexing policy")
        if parts[-1].casefold() in excluded_files or relative_path.casefold() in excluded_files:
            raise ValueError("This file is excluded by the indexing policy")
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
            result_file = DATA / "last-result.json"
            tmp = result_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.last_result), encoding="utf-8")
            tmp.replace(result_file)
            if code == 0 and not dry_run and self.config["mcp_enabled"] and not self.stopping:
                self._stop_mcp()
                self._start_mcp()

    def _schedule(self):
        while not self.stopping:
            time.sleep(30)
            with self.lock:
                if self.stopping:
                    return
                hours = self.config["interval_hours"] if self.config["onboarding_complete"] else 0
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
        try:
            with socket.create_connection(("127.0.0.1", int(os.getenv("MCP_PORT", "8000"))), timeout=1):
                mcp_reachable = True
        except OSError:
            mcp_reachable = False
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
                "app_ready": True,
                "qdrant_ready": qdrant,
                "qdrant_managed": Path("/qdrant/qdrant").exists(),
                "qdrant_running": bool(self.qdrant and self.qdrant.poll() is None) if Path("/qdrant/qdrant").exists() else qdrant,
                "mcp_running": bool(self.mcp and self.mcp.poll() is None and mcp_reachable),
                "index_running": bool(self.ingest and self.ingest.poll() is None),
                "source_ready": all(source_dir_or_false(folder) for folder in self.config["folders"]),
                "source_root": str(SOURCE),
                "upload_enabled": SOURCE == MANAGED_SOURCE,
                "last_result": self.last_result,
                "next_run_at": self.config["last_run_at"] + self.config["interval_hours"] * 3600 if self.config["interval_hours"] else None,
                "log": tail,
            }

    def close(self):
        with self.lock:
            self.stopping = True
            if self.ingest and self.ingest.poll() is None:
                self.ingest.terminate()
                try:
                    self.ingest.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.ingest.kill()
                    self.ingest.wait()
            self._stop_mcp()
            self._stop_qdrant()


controller = None


class Handler(BaseHTTPRequestHandler):
    def _authenticated(self):
        if not controller.password_enabled():
            return True
        cookie = self.headers.get("Cookie", "")
        session = next((part.split("=", 1)[1] for part in cookie.split("; ") if part.startswith("knowledge_session=")), "")
        with controller.lock:
            expiry = controller.sessions.get(session, 0)
            if expiry > time.time():
                return True
            controller.sessions.pop(session, None)
        return False

    def _allowed_host(self):
        try:
            host = urlsplit("//" + self.headers.get("Host", "")).hostname
            if host == "localhost":
                return True
            ipaddress.ip_address(host)
            return True
        except (ValueError, TypeError):
            return False

    def send(self, code, data, kind="application/json; charset=utf-8", cookie=None):
        payload = data.encode("utf-8") if isinstance(data, str) else data
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self._allowed_host():
            self.send(403, json.dumps({"error": "Host not allowed"}))
            return
        if self.path == "/api/auth":
            self.send(200, json.dumps({"required": controller.password_enabled(), "authenticated": self._authenticated()}))
            return
        if self.path == "/app.js":
            self.send(200, SCRIPT.read_text(encoding="utf-8"), "text/javascript; charset=utf-8")
            return
        if self.path == "/api/health":
            status = controller.status()
            self.send(200 if status["app_ready"] and status["qdrant_ready"] else 503, json.dumps({"app_ready": status["app_ready"], "qdrant_ready": status["qdrant_ready"], "mcp_running": status["mcp_running"]}))
            return
        if self.path == "/":
            token = TOKEN if self._authenticated() else ""
            self.send(200, HTML.read_text(encoding="utf-8").replace("__TOKEN__", token), "text/html; charset=utf-8")
            return
        if not self._authenticated():
            self.send(401, json.dumps({"error": "Login required"}))
            return
        if self.path == "/api/status":
            self.send(200, json.dumps(controller.status()))
        elif self.path == "/api/policy":
            content = POLICY.read_text(encoding="utf-8")
            self.send(200, json.dumps({"content": content, "policy": yaml.safe_load(content)}))
        elif self.path == "/api/folders":
            policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
            excluded = {x.casefold() for x in policy["exclude_directories"]}
            excluded_top = {x.casefold() for x in policy["exclude_top_level"]}
            folders = [""]
            for base, dirs, _ in os.walk(SOURCE):
                relative = Path(base).relative_to(SOURCE)
                dirs[:] = sorted(d for d in dirs if d.casefold() not in excluded and (relative.parts or d.casefold() not in excluded_top) and not (Path(base) / d).is_symlink())
                for directory in dirs:
                    folders.append((relative / directory).as_posix())
                    if len(folders) >= 500:
                        break
                if len(folders) >= 500:
                    break
            self.send(200, json.dumps({"folders": folders, "root": str(SOURCE)}))
        else:
            self.send(404, json.dumps({"error": "Not found"}))

    def do_POST(self):
        if not self._allowed_host():
            self.send(403, json.dumps({"error": "Unauthorized request"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            route = urlsplit(self.path)
            if route.path == "/api/login":
                if not 0 < length <= 4096 or not controller.password_enabled():
                    raise ValueError("Invalid login request")
                values = json.loads(self.rfile.read(length))
                address = self.client_address[0]
                with controller.lock:
                    attempts = [t for t in controller.login_attempts.get(address, []) if time.time() - t < 60]
                    if len(attempts) >= 5:
                        self.send(429, json.dumps({"error": "Try again in a minute"}))
                        return
                if not controller.check_password(values.get("password")):
                    with controller.lock:
                        controller.login_attempts[address] = attempts + [time.time()]
                    self.send(401, json.dumps({"error": "Invalid password"}))
                    return
                session = secrets.token_urlsafe(32)
                with controller.lock:
                    controller.sessions[session] = time.time() + 86400
                    controller.login_attempts.pop(address, None)
                self.send(200, json.dumps({"ok": True}), cookie=f"knowledge_session={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400")
                return
            if not self._authenticated() or self.headers.get("X-Control-Token") != TOKEN:
                self.send(403, json.dumps({"error": "Unauthorized request"}))
                return
            if route.path == "/api/logout":
                cookie = self.headers.get("Cookie", "")
                session = next((part.split("=", 1)[1] for part in cookie.split("; ") if part.startswith("knowledge_session=")), "")
                with controller.lock:
                    controller.sessions.pop(session, None)
                self.send(200, json.dumps({"ok": True}), cookie="knowledge_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                return
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
            elif self.path == "/api/security":
                if values.get("enabled") is True:
                    controller.set_password(values.get("password"))
                elif values.get("enabled") is False:
                    AUTH.unlink(missing_ok=True)
                    with controller.lock:
                        controller.sessions.clear()
                else:
                    raise ValueError("Invalid security setting")
                result = {"enabled": controller.password_enabled()}
            elif self.path == "/api/onboarding":
                controller.complete_onboarding()
                result = {"complete": True}
            elif self.path == "/api/service":
                result = controller.service(values.get("name"), values.get("action"))
            elif self.path == "/api/index":
                controller.run_index(values.get("dry_run") is True)
                result = {"started": True}
            elif self.path == "/api/policy":
                content = values.get("content")
                if isinstance(values.get("policy"), dict):
                    content = yaml.safe_dump(values["policy"], sort_keys=False, allow_unicode=True)
                if not isinstance(content, str):
                    raise ValueError("Invalid policy")
                validate_policy(content)
                with controller.lock:
                    if controller.ingest and controller.ingest.poll() is None:
                        raise ValueError("Wait until indexing finishes before changing policy")
                    tmp = POLICY.with_suffix(".tmp")
                    tmp.write_text(content, encoding="utf-8")
                    tmp.replace(POLICY)
                    controller.invalidate_result()
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
