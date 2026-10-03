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
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml
from host_sync import allowed_file, host_root, relative_path
from policy_defaults import ensure_required_exclusions


ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/data")
MANAGED_SOURCE = DATA / "documents"
HOST_SOURCE = DATA / "host-documents"
SOURCE = Path(os.getenv("KNOWLEDGE_ROOT", str(MANAGED_SOURCE))).resolve()
CONFIG = DATA / "config.json"
AUTH = DATA / "auth.json"
AGENT_AUTH = DATA / "agent-auth.json"
AGENT_MANIFEST = DATA / "agent-manifest.json"
AUTO_AGENT_CONFIG = Path(os.environ["AUTO_HOST_AGENT_CONFIG"]) if os.getenv("AUTO_HOST_AGENT_CONFIG") else None
POLICY = DATA / "index-policy.yaml"
DEFAULT_POLICY = ROOT / "mcp" / "index-policy.yaml"
HTML = Path(__file__).with_name("webui.html")
SCRIPT = Path(__file__).with_name("app.js")
TOKEN = secrets.token_urlsafe(32)


def validate_source_root(value):
    if not isinstance(value, str) or not value or (os.name != "nt" and "\\" in value):
        raise ValueError("Enter an absolute document path inside the container")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Enter an absolute document path inside the container")
    path = path.resolve()
    protected = [ROOT, DATA, *(Path(name) for name in ("/qdrant", "/proc", "/sys", "/dev", "/etc", "/run", "/root", "/usr", "/var", "/bin", "/sbin", "/lib", "/lib64", "/boot"))]
    if path == Path(path.anchor) or any(path == base or path.is_relative_to(base) for base in protected if base != DATA):
        raise ValueError("This container system path cannot be indexed")
    if path.is_relative_to(DATA) and not path.is_relative_to(MANAGED_SOURCE) and not path.is_relative_to(HOST_SOURCE):
        raise ValueError("Application data cannot be indexed")
    if not path.is_dir():
        raise ValueError(f"{path} is not visible inside the container. Mount the host folder read-only at this path and recreate the container.")
    default = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    restricted = {name.casefold() for name in default["exclude_directories"] + default["exclude_top_level"]}
    if any(part.casefold() in restricted for part in path.parts):
        raise ValueError("This path is excluded by the indexing policy")
    return path


def source_dir(subfolder, root=None):
    if not isinstance(subfolder, str) or (os.name != "nt" and "\\" in subfolder):
        raise ValueError("Invalid folder")
    root = Path(root or SOURCE).resolve()
    path = Path(subfolder)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root) or not path.is_dir():
        raise ValueError(f"Choose an existing folder inside {root}")
    return path


def normalize_folders(values, root=None):
    if not isinstance(values, list) or not values or len(values) > 32:
        raise ValueError("Choose between 1 and 32 folders")
    folders = []
    for value in values:
        root = Path(root or SOURCE).resolve()
        path = source_dir(value, root)
        relative = path.relative_to(root).as_posix()
        if relative == ".":
            relative = ""
        if relative not in folders:
            folders.append(relative)
    return folders


def source_dir_or_false(value, root=None):
    try:
        source_dir(value, root)
        return True
    except ValueError:
        return False


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as document:
        for block in iter(lambda: document.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    if type(policy.get("max_file_size_mb")) not in (int, float) or not math.isfinite(policy["max_file_size_mb"]) or not 0 < policy["max_file_size_mb"] <= 512:
        raise ValueError("max_file_size_mb must be between 0 and 512")


class Controller:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        if SOURCE == MANAGED_SOURCE:
            SOURCE.mkdir(parents=True, exist_ok=True)
        if not POLICY.exists():
            shutil.copyfile(DEFAULT_POLICY, POLICY)
        saved_policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
        if ensure_required_exclusions(saved_policy):
            tmp = POLICY.with_suffix(".tmp")
            tmp.write_text(yaml.safe_dump(saved_policy, sort_keys=False, allow_unicode=True), encoding="utf-8")
            tmp.replace(POLICY)
        self.lock = threading.RLock()
        first_start = not CONFIG.exists()
        self.config = {"source_selection": "auto", "source_mode": "host_agent" if first_start else "container", "host_root": "", "sync_revision": 0, "sync_request": 0, "source_root": str(HOST_SOURCE if first_start else SOURCE), "folders": [""], "interval_hours": 0, "mcp_enabled": False, "qdrant_enabled": True, "last_run_at": 0, "onboarding_complete": not first_start, "setup_step": 0 if first_start else 6}
        migrated = False
        if CONFIG.exists():
            stored = json.loads(CONFIG.read_text(encoding="utf-8"))
            self.config.update(stored)
            if "setup_step" not in stored and not self.config["onboarding_complete"]:
                self.config["setup_step"] = 1 if AUTH.exists() else 0
            migrated = "folders" not in stored or "source_selection" not in stored
            if "folders" not in stored:
                self.config["folders"] = [stored.get("subfolder", "")]
        if self.config["source_mode"] == "host_agent":
            HOST_SOURCE.mkdir(parents=True, exist_ok=True)
        try:
            selected_root = validate_source_root(self.config["source_root"])
            self.config["folders"] = normalize_folders(self.config["folders"], selected_root)
        except ValueError:
            # Keep the configured source when its read-only mount is temporarily absent.
            if not isinstance(self.config.get("folders"), list):
                self.config["folders"] = [""]
        self.config.pop("subfolder", None)
        if migrated:
            self._save()
        self.sessions = {}
        self.login_attempts = {}
        self.agent_seen_at = 0
        self.agent_error_text = ""
        self.sync_in_progress = False
        self.agent_manifest = json.loads(AGENT_MANIFEST.read_text(encoding="utf-8")) if AGENT_MANIFEST.exists() else {"revision": -1, "files": {}}
        self.stopping = False
        self.qdrant = None
        self.mcp = None
        self.ingest = None
        result_file = DATA / "last-result.json"
        self.last_result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else None
        if AUTO_AGENT_CONFIG is not None:
            self.setup_auto_agent()
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
            if not self.config["onboarding_complete"] and self.config["setup_step"] < 1:
                self.config["setup_step"] = 1
                self._save()

    def check_password(self, password):
        if not isinstance(password, str) or not AUTH.exists():
            return False
        record = json.loads(AUTH.read_text(encoding="utf-8"))
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(record["salt"]), 600000)
        return hmac.compare_digest(digest, bytes.fromhex(record["hash"]))

    def complete_onboarding(self):
        with self.lock:
            self.config["onboarding_complete"] = True
            self.config["setup_step"] = max(self.config["setup_step"], 5)
            self._save()

    def advance_setup(self, step):
        if type(step) is not int or not 1 <= step <= 5:
            raise ValueError("Invalid setup step")
        with self.lock:
            if not self.config["onboarding_complete"] and step > self.config["setup_step"]:
                if step != self.config["setup_step"] + 1:
                    raise ValueError("Complete the previous setup step first")
                self.config["setup_step"] = step
                self._save()
            return {"setup_step": self.config["setup_step"]}

    def invalidate_result(self):
        with self.lock:
            self.last_result = None
            (DATA / "last-result.json").unlink(missing_ok=True)

    def _env(self):
        return {**os.environ, "KNOWLEDGE_ROOT": self.config["source_root"], "INDEX_SOURCE_PATHS": json.dumps(self.config["folders"]), "POLICY_FILE": str(POLICY)}

    def agent_pair(self):
        token = secrets.token_urlsafe(48)
        with self.lock:
            tmp = AGENT_AUTH.with_suffix(".tmp")
            tmp.write_text(json.dumps({"sha256": hashlib.sha256(token.encode()).hexdigest()}), encoding="utf-8")
            tmp.replace(AGENT_AUTH)
            if os.name == "posix":
                AGENT_AUTH.chmod(0o600)
            if AUTO_AGENT_CONFIG is not None:
                self.save_auto_agent(token)
            self.agent_seen_at = 0
        return {"token": token}

    def save_auto_agent(self, token):
        AUTO_AGENT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = AUTO_AGENT_CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps({"url": "http://127.0.0.1:8080", "token": token}), encoding="utf-8")
        if os.name == "posix":
            tmp.chmod(0o600)
        tmp.replace(AUTO_AGENT_CONFIG)

    def setup_auto_agent(self):
        with self.lock:
            if AUTO_AGENT_CONFIG.exists():
                saved = json.loads(AUTO_AGENT_CONFIG.read_text(encoding="utf-8"))
                if self.agent_authenticated(saved.get("token")):
                    return
            token = secrets.token_urlsafe(48)
            tmp = AGENT_AUTH.with_suffix(".tmp")
            tmp.write_text(json.dumps({"sha256": hashlib.sha256(token.encode()).hexdigest()}), encoding="utf-8")
            if os.name == "posix":
                tmp.chmod(0o600)
            tmp.replace(AGENT_AUTH)
            self.save_auto_agent(token)

    def agent_authenticated(self, token):
        if not isinstance(token, str) or not AGENT_AUTH.exists():
            return False
        expected = json.loads(AGENT_AUTH.read_text(encoding="utf-8"))["sha256"]
        return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)

    def agent_task(self):
        with self.lock:
            self.agent_seen_at = time.time()
            return {"source_mode": self.config["source_mode"], "host_root": self.config["host_root"], "revision": self.config["sync_revision"], "sync_request": self.config["sync_request"], "index_running": bool(self.ingest and self.ingest.poll() is None), "policy": yaml.safe_load(POLICY.read_text(encoding="utf-8"))}

    def request_agent_sync(self):
        with self.lock:
            if self.config["source_mode"] != "host_agent" or not self.config["host_root"]:
                raise ValueError("Select a host folder first")
            self.config["sync_request"] += 1
            self.agent_error_text = ""
            self._save()
            return {"requested": True, "sync_request": self.config["sync_request"]}

    def agent_error(self, values):
        with self.lock:
            if values.get("revision") == self.config["sync_revision"]:
                self.agent_error_text = str(values.get("error", "Host sync failed"))[:512]
                self.sync_in_progress = False
            return {"recorded": True}

    def agent_plan(self, values):
        files = values.get("files")
        revision = values.get("revision")
        request_id = values.get("sync_request")
        if not isinstance(files, dict) or len(files) > 50000:
            raise ValueError("Invalid document inventory")
        with self.lock:
            if self.config["source_mode"] != "host_agent" or not self.config["host_root"] or revision != self.config["sync_revision"]:
                raise ValueError("Host folder changed; retry the sync")
            if type(request_id) is not int or not 0 <= request_id <= self.config["sync_request"]:
                raise ValueError("Invalid host sync request")
            if self.ingest and self.ingest.poll() is None:
                raise ValueError("Wait until indexing finishes before syncing")
            policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
            for name, item in files.items():
                if not isinstance(item, dict) or not allowed_file(name, item.get("size"), policy) or not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in item["sha256"]):
                    raise ValueError("Invalid or excluded document in inventory")
            self.sync_in_progress = True
            known = self.agent_manifest.get("files", {})
            missing = [name for name, item in files.items() if known.get(name) != item or not (HOST_SOURCE / name).is_file() or (HOST_SOURCE / name).is_symlink() or file_sha256(HOST_SOURCE / name) != item["sha256"]]
            return {"missing": missing}

    def agent_file(self, name, revision, size, digest, stream):
        path = relative_path(name)
        with self.lock:
            policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
            if self.config["source_mode"] != "host_agent" or revision != self.config["sync_revision"] or not self.sync_in_progress:
                raise ValueError("No active host sync")
            if not allowed_file(name, size, policy) or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Invalid or excluded document")
            destination = HOST_SOURCE.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents if parent != HOST_SOURCE and parent.is_relative_to(HOST_SOURCE)):
                raise ValueError("Symlink in document destination")
            temp = destination.with_name(destination.name + ".sync-" + secrets.token_hex(8))
            actual = hashlib.sha256()
            remaining = size
            try:
                with temp.open("xb") as output:
                    while remaining:
                        chunk = stream.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Incomplete document upload")
                        output.write(chunk)
                        actual.update(chunk)
                        remaining -= len(chunk)
                if actual.hexdigest() != digest:
                    raise ValueError("Document checksum mismatch")
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)

    def agent_commit(self, values):
        files = values.get("files")
        revision = values.get("revision")
        request_id = values.get("sync_request")
        if not isinstance(files, dict) or len(files) > 50000:
            raise ValueError("Invalid document inventory")
        with self.lock:
            if not self.sync_in_progress or revision != self.config["sync_revision"] or self.config["source_mode"] != "host_agent":
                raise ValueError("No active host sync")
            if type(request_id) is not int or not 0 <= request_id <= self.config["sync_request"]:
                raise ValueError("Invalid host sync request")
            policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
            for name, item in files.items():
                if not isinstance(item, dict) or not allowed_file(name, item.get("size"), policy) or not isinstance(item.get("sha256"), str):
                    raise ValueError("Invalid document inventory")
                path = HOST_SOURCE / name
                if not path.is_file() or path.is_symlink() or path.stat().st_size != item["size"] or file_sha256(path) != item["sha256"]:
                    raise ValueError(f"Document sync incomplete: {name}")
            for base, dirs, names in os.walk(HOST_SOURCE, topdown=False, followlinks=False):
                folder = Path(base)
                for name in names:
                    path = folder / name
                    if not path.is_symlink() and path.relative_to(HOST_SOURCE).as_posix() not in files:
                        path.unlink()
                for name in dirs:
                    path = folder / name
                    if not path.is_symlink() and not any(path.iterdir()):
                        path.rmdir()
            tmp = AGENT_MANIFEST.with_suffix(".tmp")
            synced_at = time.time()
            tmp.write_text(json.dumps({"revision": revision, "sync_request": request_id, "files": files, "synced_at": synced_at}), encoding="utf-8")
            tmp.replace(AGENT_MANIFEST)
            self.agent_manifest = {"revision": revision, "sync_request": request_id, "files": files, "synced_at": synced_at}
            self.sync_in_progress = False
            self.agent_error_text = ""
            return {"synced": len(files)}

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
        selection = values.get("source_selection", self.config["source_selection"])
        if "document_root" in values:
            chosen = host_root(values["document_root"])
            visible = Path(chosen).is_absolute() and Path(chosen).exists()
            mode = ("host_agent" if AUTO_AGENT_CONFIG is not None or not visible else "container") if selection == "auto" else selection
            values = {**values, "host_root" if mode == "host_agent" else "source_root": chosen}
        else:
            # Retain compatibility with clients that explicitly select a source mode.
            mode = values.get("source_mode", self.config["source_mode"])
            if "source_mode" in values:
                selection = mode
        if selection not in ("auto", "host_agent", "container"):
            raise ValueError("Invalid document location")
        if mode not in ("host_agent", "container"):
            raise ValueError("Invalid document source mode")
        if mode == "host_agent":
            selected_host = host_root(values.get("host_root", self.config["host_root"]))
            selected_root = HOST_SOURCE
            selected_root.mkdir(parents=True, exist_ok=True)
        else:
            selected_host = ""
            selected_root = validate_source_root(values.get("source_root", self.config["source_root"]))
            if selected_root.is_relative_to(HOST_SOURCE):
                raise ValueError("The host sync copy cannot be selected as a mounted folder")
        folders = normalize_folders(values.get("folders", [values["subfolder"]] if "subfolder" in values else self.config["folders"]), selected_root)
        interval = values.get("interval_hours", self.config["interval_hours"])
        if type(interval) is not int or not 0 <= interval <= 720:
            raise ValueError("Interval must be between 0 and 720 hours")
        enabled = values.get("mcp_enabled", self.config["mcp_enabled"])
        if type(enabled) is not bool:
            raise ValueError("Invalid MCP state")
        with self.lock:
            root_changed = str(selected_root) != self.config["source_root"] or selected_host != self.config["host_root"] or mode != self.config["source_mode"] or folders != self.config["folders"]
            source_changed = str(selected_root) != self.config["source_root"] or selected_host != self.config["host_root"] or mode != self.config["source_mode"]
            interval_changed = interval != self.config["interval_hours"]
            if root_changed and self.ingest and self.ingest.poll() is None:
                raise ValueError("Wait until indexing finishes before changing folders")
            self.config.update(source_selection=selection, source_mode=mode, host_root=selected_host, source_root=str(selected_root), folders=folders, interval_hours=interval, mcp_enabled=enabled)
            if source_changed:
                self.config["sync_revision"] += 1
                self.sync_in_progress = False
                self.agent_error_text = ""
            if root_changed:
                self.invalidate_result()
                if not self.config["onboarding_complete"]:
                    self.config["setup_step"] = min(self.config["setup_step"], 2)
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
            if self.config["source_mode"] == "host_agent" and not self.host_source_ready():
                raise ValueError("Wait for the host agent to finish syncing documents")
            selected_root = validate_source_root(self.config["source_root"])
            normalize_folders(self.config["folders"], selected_root)
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

    def _finish_index(self, process, dry_run):
        code = process.wait()
        with self.lock:
            self.last_result = {"exit_code": code, "dry_run": dry_run, "finished_at": time.time()}
            if code == 0 and not dry_run and self.config["setup_step"] >= 5:
                self.config["setup_step"] = 6
                self._save()
            result_file = DATA / "last-result.json"
            tmp = result_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.last_result), encoding="utf-8")
            tmp.replace(result_file)
            if code == 0 and not dry_run and self.config["mcp_enabled"] and not self.stopping:
                self._stop_mcp()
                self._start_mcp()

    def _restart_failed_services(self):
        bundled_qdrant = Path("/qdrant/qdrant").exists()
        if self.config["qdrant_enabled"] and bundled_qdrant and (self.qdrant is None or self.qdrant.poll() is not None):
            self._start_qdrant()
        if self.config["mcp_enabled"] and (not bundled_qdrant or self.config["qdrant_enabled"]) and (self.mcp is None or self.mcp.poll() is not None):
            self._start_mcp()

    def _schedule(self):
        while not self.stopping:
            time.sleep(30)
            with self.lock:
                if self.stopping:
                    return
                # Docker restarts this container when the Web UI exits. Keep the
                # separately managed child services running after their own crash.
                try:
                    self._restart_failed_services()
                except OSError as error:
                    print(f"Could not restart a service: {error}", file=sys.stderr, flush=True)
                hours = self.config["interval_hours"] if self.config["onboarding_complete"] else 0
                due_at = self.config["last_run_at"] + hours * 3600 if hours else 0
                due = hours and time.time() >= due_at
                if due and self.config["source_mode"] == "host_agent":
                    due = self.agent_manifest.get("synced_at", 0) >= due_at
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
            try:
                source_root = validate_source_root(self.config["source_root"])
                source_ready = all(source_dir_or_false(folder, source_root) for folder in self.config["folders"])
                if self.config["source_mode"] == "host_agent":
                    source_ready = source_ready and self.host_source_ready()
            except ValueError:
                source_ready = False
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
                "source_ready": source_ready,
                "agent_connected": time.time() - self.agent_seen_at < 60,
                "agent_paired": AGENT_AUTH.exists(),
                "agent_managed": AUTO_AGENT_CONFIG is not None,
                "agent_synced": self.agent_manifest.get("revision") == self.config["sync_revision"] and not self.sync_in_progress,
                "agent_syncing": self.sync_in_progress,
                "agent_error": self.agent_error_text,
                "agent_last_sync_at": self.agent_manifest.get("synced_at"),
                "agent_file_count": len(self.agent_manifest.get("files", {})) if self.agent_manifest.get("revision") == self.config["sync_revision"] else 0,
                "agent_sync_request_completed": self.agent_manifest.get("sync_request", -1),
                "source_root": self.config["source_root"],
                "last_result": self.last_result,
                "next_run_at": self.config["last_run_at"] + self.config["interval_hours"] * 3600 if self.config["interval_hours"] else None,
                "log": tail,
            }

    def host_source_ready(self):
        return bool(self.config["host_root"] and self.agent_manifest.get("revision") == self.config["sync_revision"] and not self.sync_in_progress and not self.agent_error_text and time.time() - self.agent_seen_at < 60)

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
        if self.path == "/api/agent/task":
            if not controller.agent_authenticated(self.headers.get("X-Agent-Token")):
                self.send(403, json.dumps({"error": "Host agent not paired"}))
                return
            self.send(200, json.dumps(controller.agent_task()))
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
            root = Path(controller.config["source_root"])
            if controller.config["source_mode"] == "host_agent" and not controller.host_source_ready():
                self.send(200, json.dumps({"folders": [""], "root": controller.config["host_root"]}))
                return
            policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
            excluded = {x.casefold() for x in policy["exclude_directories"]}
            excluded_top = {x.casefold() for x in policy["exclude_top_level"]}
            folders = [""]
            for base, dirs, _ in os.walk(root):
                relative = Path(base).relative_to(root)
                dirs[:] = sorted(d for d in dirs if d.casefold() not in excluded and (relative.parts or d.casefold() not in excluded_top) and not (Path(base) / d).is_symlink())
                for directory in dirs:
                    folders.append((relative / directory).as_posix())
                    if len(folders) >= 500:
                        break
                if len(folders) >= 500:
                    break
            self.send(200, json.dumps({"folders": folders, "root": str(root)}))
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
            if route.path.startswith("/api/agent/") and route.path not in ("/api/agent/pair", "/api/agent/refresh"):
                if not controller.agent_authenticated(self.headers.get("X-Agent-Token")):
                    self.send(403, json.dumps({"error": "Host agent not paired"}))
                    return
                if route.path == "/api/agent/file":
                    query = parse_qs(route.query)
                    name = query.get("path", [""])[0]
                    revision = int(self.headers.get("X-Sync-Revision", "-1"))
                    controller.agent_file(name, revision, length, self.headers.get("X-File-Sha256"), self.rfile)
                    self.send(200, json.dumps({"saved": True}))
                    return
                if not 0 < length <= 8 * 1024 * 1024:
                    raise ValueError("Document inventory is too large or empty")
                values = json.loads(self.rfile.read(length))
                if not isinstance(values, dict):
                    raise ValueError("Invalid document inventory")
                if route.path == "/api/agent/plan":
                    result = controller.agent_plan(values)
                elif route.path == "/api/agent/commit":
                    result = controller.agent_commit(values)
                elif route.path == "/api/agent/error":
                    result = controller.agent_error(values)
                else:
                    self.send(404, json.dumps({"error": "Not found"}))
                    return
                self.send(200, json.dumps(result))
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
                self.send(404, json.dumps({"error": "Document uploads are unavailable"}))
                return
            if not 0 < length <= 65536:
                raise ValueError("Request is too large or empty")
            values = json.loads(self.rfile.read(length))
            if not isinstance(values, dict):
                raise ValueError("Invalid data")
            if self.path == "/api/config":
                result = controller.update(values)
            elif self.path == "/api/agent/pair":
                result = controller.agent_pair()
            elif self.path == "/api/agent/refresh":
                result = controller.request_agent_sync()
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
            elif self.path == "/api/onboarding/progress":
                result = controller.advance_setup(values.get("step"))
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
                    if not controller.config["onboarding_complete"]:
                        controller.config["setup_step"] = min(controller.config["setup_step"], 3)
                        controller._save()
                    if controller.config["source_mode"] == "host_agent":
                        controller.config["sync_revision"] += 1
                        controller.sync_in_progress = False
                        controller._save()
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
