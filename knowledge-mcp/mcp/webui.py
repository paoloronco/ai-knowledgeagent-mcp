import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DATA = Path("/data")
SOURCE = Path("/knowledge").resolve()
CONFIG = DATA / "config.json"
POLICY = DATA / "index-policy.yaml"
DEFAULT_POLICY = ROOT / "mcp" / "index-policy.yaml"
HTML = Path(__file__).with_name("webui.html")
TOKEN = secrets.token_urlsafe(32)


def source_dir(subfolder):
    if not isinstance(subfolder, str) or "\\" in subfolder:
        raise ValueError("Cartella non valida")
    path = (SOURCE / subfolder).resolve()
    if not path.is_relative_to(SOURCE) or not path.is_dir():
        raise ValueError("Scegli una cartella esistente dentro il percorso montato")
    return path


def validate_policy(content):
    policy = yaml.safe_load(content)
    default = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError("La policy deve essere un oggetto YAML")
    for key in ("exclude_directories", "exclude_top_level", "exclude_extensions"):
        actual = policy.get(key)
        if not isinstance(actual, list) or not all(isinstance(x, str) for x in actual):
            raise ValueError(f"{key} deve essere un elenco")
        required = set(default[key]) if key == "exclude_extensions" else {x.casefold() for x in default[key]}
        present = set(actual) if key == "exclude_extensions" else {x.casefold() for x in actual}
        if not required <= present:
            raise ValueError(f"Non rimuovere le esclusioni predefinite da {key}")
    if not isinstance(policy.get("include_extensions"), list) or not all(isinstance(x, str) for x in policy["include_extensions"]):
        raise ValueError("include_extensions deve essere un elenco")
    if type(policy.get("max_file_size_mb")) not in (int, float) or policy["max_file_size_mb"] <= 0:
        raise ValueError("max_file_size_mb deve essere un numero positivo")


class Controller:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
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
        return {**os.environ, "KNOWLEDGE_ROOT": str(source_dir(self.config["subfolder"])), "POLICY_FILE": str(POLICY)}

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
            raise ValueError("L'intervallo deve essere tra 0 e 720 ore")
        enabled = values.get("mcp_enabled", self.config["mcp_enabled"])
        if type(enabled) is not bool:
            raise ValueError("Stato MCP non valido")
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
                raise ValueError("Indicizzazione già in corso")
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
    def _local_host(self):
        return self.headers.get("Host", "").split(":", 1)[0].lower() in ("localhost", "127.0.0.1")

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
        if not self._local_host():
            self.send(403, json.dumps({"error": "Host non consentito"}))
            return
        if self.path == "/":
            self.send(200, HTML.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self.send(200, json.dumps(controller.status()))
        elif self.path == "/api/policy":
            self.send(200, json.dumps({"content": POLICY.read_text(encoding="utf-8")}))
        else:
            self.send(404, json.dumps({"error": "Non trovato"}))

    def do_POST(self):
        if not self._local_host() or self.headers.get("X-Control-Token") != TOKEN:
            self.send(403, json.dumps({"error": "Richiesta non autorizzata"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("Richiesta troppo grande o vuota")
            values = json.loads(self.rfile.read(length))
            if not isinstance(values, dict):
                raise ValueError("Dati non validi")
            if self.path == "/api/config":
                result = controller.update(values)
            elif self.path == "/api/index":
                controller.run_index(values.get("dry_run") is True)
                result = {"started": True}
            elif self.path == "/api/policy":
                content = values.get("content")
                if not isinstance(content, str):
                    raise ValueError("Policy non valida")
                validate_policy(content)
                tmp = POLICY.with_suffix(".tmp")
                tmp.write_text(content, encoding="utf-8")
                tmp.replace(POLICY)
                result = {"saved": True}
            else:
                self.send(404, json.dumps({"error": "Non trovato"}))
                return
            self.send(200, json.dumps(result))
        except (ValueError, yaml.YAMLError) as exc:
            self.send(400, json.dumps({"error": str(exc)}))
        except Exception:
            self.send(500, json.dumps({"error": "Errore interno; controlla i log del container"}))
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
