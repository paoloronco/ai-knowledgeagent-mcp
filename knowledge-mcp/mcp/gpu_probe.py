"""Inspect NVIDIA visibility and PyTorch CUDA support outside the Web UI process."""

import csv
import importlib.metadata
import json
import subprocess
import sys
import threading
import time
from pathlib import Path


def parse_devices(output):
    devices = []
    for row in csv.reader(output.splitlines(), skipinitialspace=True):
        if len(row) != 5:
            continue
        index, name, driver, total, free = (field.strip() for field in row)
        try:
            devices.append({"index": int(index), "name": name, "driver": driver,
                            "memory_total_mb": int(total), "memory_free_mb": int(free)})
        except ValueError:
            continue
    return devices


def probe_gpu():
    try:
        torch_version = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError:
        torch_version = None
    result = {"detected": False, "usable": False, "devices": [], "torch_version": torch_version,
              "cuda_runtime": None, "reason": "No NVIDIA GPU is exposed to the application container."}
    try:
        command = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,driver_version,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        command = None
    if command is not None and command.returncode == 0:
        result["devices"] = parse_devices(command.stdout)
    if not result["devices"] and "+cu" not in (torch_version or ""):
        return result
    result["detected"] = bool(result["devices"])
    try:
        import torch
        result["cuda_runtime"] = torch.version.cuda
        result["usable"] = bool(torch.cuda.is_available())
        if result["usable"] and not result["devices"]:
            free, total = torch.cuda.mem_get_info(0)
            result["devices"] = [{"index": 0, "name": torch.cuda.get_device_name(0), "driver": "unknown",
                                  "memory_total_mb": total // 1048576, "memory_free_mb": free // 1048576}]
        result["detected"] = bool(result["devices"])
        if result["usable"]:
            result["reason"] = "CUDA ready."
        elif not result["devices"]:
            result["reason"] = "No NVIDIA GPU is exposed to the application container."
        elif torch.version.cuda is None:
            result["reason"] = "This image has CPU-only PyTorch. Use the CUDA image and expose the GPU to Docker."
        else:
            result["reason"] = "PyTorch cannot initialize CUDA with the exposed GPU and driver."
    except Exception:
        result["reason"] = "PyTorch could not initialize CUDA with the exposed GPU."
    return result


class GpuMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_checked = 0
        self.running = False
        self.value = {"checking": True, "detected": False, "usable": False, "devices": []}

    def status(self):
        with self.lock:
            if not self.running and time.monotonic() - self.last_checked > 30:
                self.running = True
                threading.Thread(target=self._refresh, daemon=True).start()
            return dict(self.value)

    def _refresh(self):
        try:
            command = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                capture_output=True, text=True, timeout=20, check=True,
            )
            value = json.loads(command.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            value = {"detected": False, "usable": False, "devices": [],
                     "reason": "GPU detection is temporarily unavailable."}
        with self.lock:
            self.value = {**value, "checking": False}
            self.last_checked = time.monotonic()
            self.running = False


GPU_MONITOR = GpuMonitor()


if __name__ == "__main__":
    print(json.dumps(probe_gpu()))
