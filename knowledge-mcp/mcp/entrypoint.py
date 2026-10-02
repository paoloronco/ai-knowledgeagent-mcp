"""Run the bundled Qdrant server and Web UI in one container."""

import signal
import subprocess
import sys
import time


def main():
    qdrant = subprocess.Popen(["/qdrant/qdrant"], cwd="/qdrant")
    webui = subprocess.Popen([sys.executable, "mcp/webui.py"], cwd="/app")
    children = (qdrant, webui)
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
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
