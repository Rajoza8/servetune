"""Read-only identification of the GPU used by ServeTune preflight."""
from __future__ import annotations

import csv
import importlib.metadata
import io
import math
import platform
import shutil
import subprocess


def _version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def probe_hardware(gpu_index: int = 0) -> dict:
    """Probe one physical GPU without root or changes to clocks/power settings.

    A missing driver/tool is ``blocked``. A different GPU, occupied GPU, or
    missing serving package is ``fail``. The commands and bounded raw output
    are retained as evidence; no environment variables are read or returned.
    """
    if type(gpu_index) is not int or gpu_index < 0:
        raise ValueError("gpu_index must be a nonnegative integer")
    result = {
        "status": "blocked", "platform": platform.system(),
        "machine": platform.machine(), "gpu_index": gpu_index,
        "gpu": None, "driver_version": None,
        "vllm_version": _version("vllm"), "processes": [],
        "commands": [], "blockers": [],
    }
    executable = shutil.which("nvidia-smi")
    if not executable:
        result["blockers"].append("nvidia-smi is unavailable; run live preflight on the NVIDIA GPU host")
        return result

    def run(fields: str, *, applications: bool = False) -> subprocess.CompletedProcess:
        query = "--query-compute-apps=" if applications else "--query-gpu="
        command = [executable, "-i", str(gpu_index), query + fields,
                   "--format=csv,noheader,nounits"]
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=10, check=False)
        if len(completed.stdout) > 65536 or len(completed.stderr) > 65536:
            raise ValueError("nvidia-smi returned unexpectedly large output")
        result["commands"].append({"argv": command, "returncode": completed.returncode,
                                   "stdout": completed.stdout, "stderr": completed.stderr})
        return completed

    try:
        completed = run("index,uuid,name,driver_version,memory.total,memory.used,compute_cap")
        if completed.returncode:
            result["blockers"].append("nvidia-smi could not query the selected GPU")
            return result
        rows = list(csv.reader(io.StringIO(completed.stdout)))
        if len(rows) != 1 or len(rows[0]) != 7:
            raise ValueError("Expected exactly one seven-field GPU identification record")
        index, uuid, name, driver, total, used, capability = [value.strip() for value in rows[0]]
        gpu = {"index": int(index), "uuid": uuid, "name": name,
               "total_memory_mib": float(total), "used_memory_mib": float(used),
               "compute_capability": capability}
        if (gpu["index"] != gpu_index or not uuid.startswith("GPU-") or not driver
                or not math.isfinite(gpu["total_memory_mib"])
                or not math.isfinite(gpu["used_memory_mib"])
                or not 0 <= gpu["used_memory_mib"] <= gpu["total_memory_mib"]):
            raise ValueError("Inconsistent GPU identification record")
        result["gpu"], result["driver_version"] = gpu, driver
        result["status"] = "pass"
        if "RTX PRO 6000" not in name.upper() or "BLACKWELL" not in name.upper():
            result["blockers"].append("Selected GPU is not the specified RTX PRO 6000 Blackwell")
        if gpu["total_memory_mib"] < 90000 or capability != "12.0":
            result["blockers"].append("Expected approximately 96 GB VRAM and SM120")
        applications = run("pid,process_name,used_memory,gpu_uuid", applications=True)
        if applications.returncode:
            result["blockers"].append("Cannot verify exclusive GPU access from process telemetry")
        else:
            for row in csv.reader(io.StringIO(applications.stdout)):
                if not row or all(not field.strip() for field in row):
                    continue
                if len(row) != 4:
                    raise ValueError("Malformed GPU process record")
                pid, process_name, memory, gpu_uuid = [field.strip() for field in row]
                if gpu_uuid == uuid:
                    result["processes"].append({"pid": int(pid), "process_name": process_name,
                                                 "used_memory_mib": memory, "gpu_uuid": gpu_uuid})
            if result["processes"]:
                result["blockers"].append("GPU has existing compute processes; exclusive measurement is not established")
        if result["vllm_version"] is None:
            result["blockers"].append("vLLM is not installed in this Python environment")
        if result["blockers"]:
            result["status"] = "fail"
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        result["status"] = "blocked" if result["gpu"] is None else "fail"
        result["blockers"].append(f"Hardware probe failed: {type(exc).__name__}")
    return result
