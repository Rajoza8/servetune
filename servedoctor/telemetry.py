"""Once-per-second incident telemetry: vLLM Prometheus metrics, NVML GPU state,
client-side request outcomes, gateway policy and filtered engine log lines.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import threading
import time
import urllib.request

# vLLM renamed several metrics across releases; each alias set maps to one field.
GAUGES = {
    "running": ("vllm:num_requests_running",),
    "waiting": ("vllm:num_requests_waiting",),
    "kv_usage": ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"),
}
COUNTERS = {
    "preemptions_total": ("vllm:num_preemptions_total", "vllm:num_preemptions"),
    "prompt_tokens_total": ("vllm:prompt_tokens_total", "vllm:prompt_tokens"),
    "generation_tokens_total": ("vllm:generation_tokens_total", "vllm:generation_tokens"),
    "request_success_total": ("vllm:request_success_total", "vllm:request_success"),
}
HISTOGRAMS = {
    "ttft": "vllm:time_to_first_token_seconds",
    "e2e": "vllm:e2e_request_latency_seconds",
    "queue": "vllm:request_queue_time_seconds",
    "prefill": "vllm:request_prefill_time_seconds",
}
_LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)")


def parse_prometheus(text):
    """Sum each metric family across labels; histograms keep _sum and _count only."""
    totals = {}
    for raw in text.splitlines():
        if not raw or raw.startswith("#"):
            continue
        match = _LINE.match(raw)
        if not match:
            continue
        name, value = match.group(1), match.group(3)
        if not name.startswith("vllm:") or name.endswith("_bucket") or name.endswith("_created"):
            continue
        try:
            number = float(value)
        except ValueError:
            continue
        if math.isfinite(number):
            totals[name] = totals.get(name, 0.0) + number
    out = {}
    for field, names in {**GAUGES, **COUNTERS}.items():
        for name in names:
            if name in totals:
                out[field] = totals[name]
                break
    if "kv_usage" in out and out["kv_usage"] <= 1.0:
        out["kv_usage"] = out["kv_usage"] * 100  # Report as percent regardless of version.
    for field, name in HISTOGRAMS.items():
        if name + "_count" in totals:
            out[field + "_sum"] = totals.get(name + "_sum", 0.0)
            out[field + "_count"] = totals[name + "_count"]
    return out


def scrape_metrics(url, timeout=2.0):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return parse_prometheus(response.read(4_000_000).decode("utf-8", "replace"))


def _cmdline(pid):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    parts = [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
    return " ".join(parts)[:120] if parts else None


class GpuSampler:
    """NVML snapshot of power, utilization, memory, clocks and GPU processes."""
    def __init__(self, gpu_index=0, _nvml=None):
        self.gpu_index = gpu_index
        self._nvml = _nvml
        self._handle = None

    def start(self):
        if self._nvml is None:
            import pynvml
            self._nvml = pynvml
        self._nvml.nvmlInit()
        self._handle = self._nvml.nvmlDeviceGetHandleByIndex(self.gpu_index)
        return self

    def sample(self):
        nv, h = self._nvml, self._handle
        row = {}
        for key, fn in (("power_w", lambda: nv.nvmlDeviceGetPowerUsage(h) / 1000),
                        ("energy_mj", lambda: nv.nvmlDeviceGetTotalEnergyConsumption(h)),
                        ("temp_c", lambda: nv.nvmlDeviceGetTemperature(h, 0)),
                        ("sm_clock_mhz", lambda: nv.nvmlDeviceGetClockInfo(h, 1))):
            try:
                row[key] = fn()
            except Exception:
                row[key] = None
        try:
            util = nv.nvmlDeviceGetUtilizationRates(h)
            row["util_gpu"], row["util_mem"] = util.gpu, util.memory
        except Exception:
            row["util_gpu"] = row["util_mem"] = None
        try:
            mem = nv.nvmlDeviceGetMemoryInfo(h)
            row["mem_used_mb"], row["mem_total_mb"] = mem.used // 2**20, mem.total // 2**20
        except Exception:
            row["mem_used_mb"] = row["mem_total_mb"] = None
        processes = []
        try:
            for proc in nv.nvmlDeviceGetComputeRunningProcesses(h):
                used = getattr(proc, "usedGpuMemory", None)
                processes.append({"pid": int(proc.pid),
                                  "used_mb": int(used // 2**20) if isinstance(used, int) else None,
                                  "command": _cmdline(proc.pid)})
        except Exception:
            pass
        row["processes"] = sorted(processes, key=lambda p: p["pid"])
        return row

    def stop(self):
        try:
            self._nvml.nvmlShutdown()
        except Exception:
            pass


class LogTail:
    """Return new engine log lines that look operationally relevant."""
    KEEP = re.compile(r"WARNING|ERROR|Traceback|throughput|preempt|maximum context length|out of memory|CUDA",
                      re.IGNORECASE)

    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0

    def read(self, limit=20):
        if not self.path.exists():
            return []
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            chunk = stream.read(2_000_000)
        cut = chunk.rfind(b"\n")
        if cut < 0:
            return []
        self.offset += cut + 1
        lines = chunk[:cut].decode("utf-8", "replace").splitlines()
        return [line[:300] for line in lines if self.KEEP.search(line)][:limit]


class Recorder:
    """Write one JSON line per second until stopped. All sources are optional."""
    def __init__(self, out_path, *, clock_zero, metrics_url=None, gpu=None, loadgen=None,
                 gateway=None, log_tail=None, config_fn=None, interval_s=1.0, scrape=scrape_metrics):
        self.out_path = Path(out_path)
        self.clock_zero = clock_zero
        self.metrics_url, self.gpu, self.loadgen = metrics_url, gpu, loadgen
        self.gateway, self.log_tail, self.config_fn = gateway, log_tail, config_fn
        self.interval_s, self.scrape = interval_s, scrape
        self._stop = threading.Event()
        self._thread = None
        self.rows = 0
        self.errors = 0

    def snapshot(self):
        t = time.monotonic() - self.clock_zero
        row = {"t": round(t, 3)}
        if self.metrics_url:
            try:
                row["vllm"] = self.scrape(self.metrics_url)
            except Exception as exc:
                row["vllm"] = {"scrape_error": type(exc).__name__}
                self.errors += 1
        if self.gpu is not None:
            try:
                row["gpu"] = self.gpu.sample()
            except Exception as exc:
                row["gpu"] = {"sample_error": type(exc).__name__}
                self.errors += 1
        if self.loadgen is not None:
            row["client"] = self.loadgen.drain_window()
        if self.gateway is not None:
            row["gateway"] = self.gateway.policy()
        if self.config_fn is not None:
            row["engine_config"] = self.config_fn()
        if self.log_tail is not None:
            row["log"] = self.log_tail.read()
        return row

    def _loop(self, stream):
        next_tick = time.monotonic()
        while not self._stop.is_set():
            stream.write(json.dumps(self.snapshot(), allow_nan=False) + "\n")
            stream.flush()
            self.rows += 1
            next_tick += self.interval_s
            self._stop.wait(max(0.0, next_tick - time.monotonic()))

    def start(self):
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.out_path.open("x", encoding="utf-8")

        def run():
            try:
                self._loop(stream)
            finally:
                stream.close()

        self._thread = threading.Thread(target=run, name="servedoctor-recorder", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def environment_marker_matches(pid, marker):
    try:
        return marker.encode() in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False


def pid_exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
