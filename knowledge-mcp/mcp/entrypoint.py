"""Run the Web UI, which supervises bundled Qdrant and MCP."""

import signal
import subprocess
import sys
import time


def main():
    webui = subprocess.Popen([sys.executable, "mcp/webui.py"], cwd="/app")
    children = (webui,)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            for child in children:
                if child.poll() is not None:
                    return child.returncode or 1
            time.sleep(0.5)
        return 0
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
