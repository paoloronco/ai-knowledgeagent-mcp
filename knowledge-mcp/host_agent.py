"""Host-side document companion. Runs outside Docker with Python 3.10+."""

import argparse
import getpass
import hashlib
import http.client
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "mcp"))
from host_sync import allowed_file, host_root


DEFAULT_CONFIG = Path.home() / ".config" / "knowledge-mcp" / "agent.json"
LOG = logging.getLogger("knowledge-host-agent")


def request(base, token, route, payload=None, headers=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"X-Agent-Token": token, **(headers or {})}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + route, data=body, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            message = json.load(error).get("error", error.reason)
        except (ValueError, OSError):
            message = error.reason
        raise RuntimeError(f"Dashboard returned {error.code}: {message}") from error


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as document:
        for block in iter(lambda: document.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root, policy):
    folder = Path(host_root(root)).expanduser()
    if not folder.is_dir():
        raise ValueError(f"Host folder is unavailable: {folder}")
    folder = folder.resolve()
    if folder == Path(folder.anchor):
        raise ValueError("Choose a folder, not a filesystem root")
    restricted = {x.casefold() for x in policy["exclude_directories"] + policy["exclude_top_level"]}
    if any(part.casefold() in restricted for part in folder.parts):
        raise ValueError("The selected host folder is excluded by the indexing policy")
    files = {}
    for base, dirs, names in os.walk(folder, followlinks=False):
        current = Path(base)
        relative_dir = current.relative_to(folder)
        dirs[:] = sorted(name for name in dirs if not (current / name).is_symlink() and name.casefold() not in restricted and (relative_dir.parts or name.casefold() not in {x.casefold() for x in policy["exclude_top_level"]}))
        for name in sorted(names):
            path = current / name
            if path.is_symlink():
                continue
            relative = path.relative_to(folder).as_posix()
            try:
                size = path.stat().st_size
                if allowed_file(relative, size, policy):
                    files[relative] = {"size": size, "sha256": file_hash(path)}
            except (OSError, ValueError) as error:
                raise RuntimeError(f"Could not read {path}: {error}") from error
    return folder, files


def sync(base, token, task):
    folder, files = inventory(task["host_root"], task["policy"])
    body = {"revision": task["revision"], "files": files}
    missing = request(base, token, "/api/agent/plan", body)["missing"]
    for name in missing:
        document = folder.joinpath(*name.split("/"))
        if document.is_symlink() or not document.resolve().is_relative_to(folder):
            raise ValueError("Document changed to a symlink during sync")
        send_file(base, token, task["revision"], name, document, files[name])
    result = request(base, token, "/api/agent/commit", body)
    LOG.info("Synced %s documents (%s transferred)", result["synced"], len(missing))


def send_file(base, token, revision, name, document, info):
    parsed = urllib.parse.urlsplit(base)
    connection = (http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection)(parsed.hostname, parsed.port, timeout=120)
    remaining = info["size"]
    digest = hashlib.sha256()
    try:
        connection.putrequest("POST", "/api/agent/file?path=" + urllib.parse.quote(name, safe=""))
        connection.putheader("X-Agent-Token", token)
        connection.putheader("X-Sync-Revision", str(revision))
        connection.putheader("X-File-Sha256", info["sha256"])
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", str(remaining))
        connection.endheaders()
        with document.open("rb") as source:
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise RuntimeError(f"Document changed during sync: {name}")
                connection.send(block)
                digest.update(block)
                remaining -= len(block)
        response = connection.getresponse()
        body = response.read()
        if response.status != 200 or digest.hexdigest() != info["sha256"]:
            raise RuntimeError(f"Document transfer failed for {name}: {body.decode(errors='replace')}")
    finally:
        connection.close()


def validate_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Use only the dashboard origin, such as http://127.0.0.1:8080")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Use HTTPS unless the dashboard is on this host's loopback address")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid dashboard URL")
    return value.rstrip("/")


def run(config_path, once=False, scan_seconds=300):
    last_signature = None
    last_scan = 0
    while True:
        task = None
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            base = validate_url(config["url"])
            token = config["token"]
            task = request(base, token, "/api/agent/task")
            signature = (task["revision"], task["sync_request"], json.dumps(task["policy"], sort_keys=True))
            if task["source_mode"] == "host_agent" and task["host_root"] and (signature != last_signature or time.time() - last_scan >= scan_seconds):
                sync(base, token, task)
                last_signature = signature
                last_scan = time.time()
            if once:
                return
        except Exception as error:
            LOG.exception("Host sync failed; retrying")
            if task and task.get("source_mode") == "host_agent":
                try:
                    request(base, token, "/api/agent/error", {"revision": task["revision"], "error": str(error)})
                except Exception:
                    pass
            if once:
                raise
        time.sleep(15)


def install(url, config_path):
    base = validate_url(url)
    token = getpass.getpass("Pairing key from the dashboard: ").strip()
    if not token:
        raise ValueError("Pairing key is required")
    request(base, token, "/api/agent/task")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"url": base, "token": token}), encoding="utf-8")
    if os.name == "posix":
        config_path.chmod(0o600)
        unit = Path.home() / ".config" / "systemd" / "user" / "knowledge-mcp-agent.service"
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text("[Unit]\nDescription=Knowledge MCP host document agent\nAfter=network-online.target\n\n[Service]\nExecStart=\"" + sys.executable + "\" \"" + str(Path(__file__).resolve()) + "\" run --config \"" + str(config_path) + "\"\nRestart=always\nRestartSec=10\n\n[Install]\nWantedBy=default.target\n", encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "knowledge-mcp-agent.service"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "knowledge-mcp-agent.service"], check=True)
        linger = subprocess.run(["loginctl", "enable-linger", getpass.getuser()], capture_output=True, text=True)
        if linger.returncode:
            print(f"To keep the agent running after logout and start it at boot, run: sudo loginctl enable-linger {getpass.getuser()}")
        print("Host agent installed and started. It runs under your user account.")
    elif os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = pythonw if pythonw.exists() else Path(sys.executable)
        command = f'"{executable}" "{Path(__file__).resolve()}" run --config "{config_path}"'
        subprocess.run(["schtasks", "/Create", "/SC", "ONLOGON", "/TN", "KnowledgeMCPHostAgent", "/TR", command, "/F"], check=True)
        subprocess.run(["schtasks", "/Run", "/TN", "KnowledgeMCPHostAgent"], check=True)
        print("Host agent installed and started. It restarts when you sign in.")
    else:
        print(f"Config saved at {config_path}. Run: {sys.executable} {Path(__file__).resolve()} run --config {config_path}")


def main():
    parser = argparse.ArgumentParser(description="Sync a host document folder selected in Knowledge MCP")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("install", help="Pair and install a per-user background service")
    setup.add_argument("--url", default="http://127.0.0.1:8080")
    setup.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    serve = commands.add_parser("run", help="Run the background agent")
    serve.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    serve.add_argument("--once", action="store_true")
    serve.add_argument("--scan-seconds", type=int, default=300)
    args = parser.parse_args()
    DEFAULT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=DEFAULT_CONFIG.parent / "agent.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "install":
        install(args.url, args.config)
    else:
        run(args.config, args.once, args.scan_seconds)


if __name__ == "__main__":
    main()
