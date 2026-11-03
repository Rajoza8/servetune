"""Whitelisted local vLLM lifecycle. No shell execution or foreign PID control."""
from __future__ import annotations

import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request


class EngineError(RuntimeError):
    pass


_KEYS = {
    "model_id", "model_revision", "tokenizer_revision", "host", "port",
    "engine_executable", "startup_timeout_s", "request_timeout_s", "gpu_index",
    "max_model_len", "max_num_seqs", "max_num_batched_tokens",
    "gpu_memory_utilization", "enable_chunked_prefill", "fp8_quantization",
    "enable_prefix_caching", "gpu_uuid", "use_engine_defaults",
}
_REVISION = re.compile(r"[a-fA-F0-9]{40}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_DEFAULTS = {
    "host": "127.0.0.1", "port": 8000, "engine_executable": "vllm",
    "startup_timeout_s": 600, "request_timeout_s": 120, "gpu_index": 0,
    "max_model_len": 4096, "max_num_seqs": 8, "max_num_batched_tokens": 4096,
    "gpu_memory_utilization": 0.9, "enable_chunked_prefill": True,
    "fp8_quantization": "fp8_per_tensor", "enable_prefix_caching": False,
    "use_engine_defaults": False,
}


def validate_engine_config(config: dict) -> dict:
    if type(config) is not dict or set(config) - _KEYS:
        raise ValueError("Engine config has unknown keys or is not an object")
    value = {**_DEFAULTS, **config}
    if (type(value.get("model_id")) is not str or not _MODEL.fullmatch(value["model_id"])
            or type(value.get("model_revision")) is not str
            or not _REVISION.fullmatch(value["model_revision"])):
        raise ValueError("Live serving requires a Hub model ID and an exact 40-character revision hash")
    if value.get("tokenizer_revision") is not None and (
            type(value["tokenizer_revision"]) is not str
            or not _REVISION.fullmatch(value["tokenizer_revision"])):
        raise ValueError("tokenizer_revision must be an exact revision hash")
    if value["host"] != "127.0.0.1":
        raise ValueError("Preflight serving is restricted to loopback")
    if value.get("gpu_uuid") is not None and (
            type(value["gpu_uuid"]) is not str
            or not re.fullmatch(r"GPU-[A-Za-z0-9-]+", value["gpu_uuid"])):
        raise ValueError("gpu_uuid must be a physical NVIDIA GPU UUID")
    executable = value["engine_executable"]
    if (type(executable) is not str or Path(executable).name != "vllm"
            or ("/" in executable and not Path(executable).is_absolute())):
        raise ValueError("engine_executable must be vllm or an absolute path to vllm")
    limits = {"port": (1024, 65535), "gpu_index": (0, 1023),
              "max_model_len": (32, 131072), "max_num_seqs": (1, 1024),
              "max_num_batched_tokens": (32, 131072)}
    for name, (lower, upper) in limits.items():
        if type(value[name]) is not int or not lower <= value[name] <= upper:
            raise ValueError(f"{name} must be an integer in [{lower}, {upper}]")
    for name, upper in (("startup_timeout_s", 3600), ("request_timeout_s", 600)):
        item = value[name]
        if (isinstance(item, bool) or not isinstance(item, (int, float))
                or not math.isfinite(item) or not 1 <= item <= upper):
            raise ValueError(f"{name} must be finite and between 1 and {upper} seconds")
    memory = value["gpu_memory_utilization"]
    if (isinstance(memory, bool) or not isinstance(memory, (int, float))
            or not math.isfinite(memory) or not 0.1 <= memory <= 0.95):
        raise ValueError("gpu_memory_utilization must be finite and between 0.1 and 0.95")
    for name in ("enable_chunked_prefill", "enable_prefix_caching", "use_engine_defaults"):
        if type(value[name]) is not bool:
            raise ValueError(f"{name} must be boolean")
    if value["fp8_quantization"] != "fp8_per_tensor":
        raise ValueError("Only the documented online fp8_per_tensor quantization is enabled")
    return value


def engine_command(config: dict, dtype: str = "bf16") -> list[str]:
    value = validate_engine_config(config)
    if dtype not in {"bf16", "fp8"}:
        raise ValueError("dtype must be bf16 or fp8")
    command = [value["engine_executable"], "serve", value["model_id"],
               "--revision", value["model_revision"],
               "--served-model-name", "servetune-glimmer", "--host", value["host"],
               "--port", str(value["port"]), "--dtype", "bfloat16",
               "--tensor-parallel-size", "1", "--generation-config", "auto",
               "--reasoning-parser", "muse_glimmer", "--seed", "0"]
    tokenizer_revision = value.get("tokenizer_revision") or value["model_revision"]
    command += ["--tokenizer-revision", tokenizer_revision]
    knob_names = ["max_model_len"]
    if not value["use_engine_defaults"]:
        knob_names += ["max_num_seqs", "max_num_batched_tokens", "gpu_memory_utilization"]
    for name in knob_names:
        command += ["--" + name.replace("_", "-"), str(value[name])]
    boolean_names = ["enable_prefix_caching"]
    if not value["use_engine_defaults"]:
        boolean_names.append("enable_chunked_prefill")
    for name in boolean_names:
        command.append("--" + ("" if value[name] else "no-") + name.replace("_", "-"))
    if dtype == "fp8":
        command += ["--quantization", value["fp8_quantization"]]
    return command


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EngineError("Local engine health endpoint attempted a redirect")


class ManagedEngine:
    """Start and stop only the vLLM process group created by this instance."""
    def __init__(self, config: dict, artifact_dir: Path, dtype: str = "bf16"):
        self.config = validate_engine_config(config)
        self.command = engine_command(self.config, dtype)
        self.artifact_dir = Path(artifact_dir)
        self.dtype = dtype
        self.base_url = f"http://127.0.0.1:{self.config['port']}/v1"
        self._process = None
        self._log = None
        self._started_once = False
        self._owned_pgid = None
        self._owned_session = None
        self._owner_marker = secrets.token_hex(16)
        self._proc_root = Path("/proc")
        try:
            version = importlib.metadata.version("vllm")
        except importlib.metadata.PackageNotFoundError:
            version = None
        executable_path = shutil.which(self.config["engine_executable"])
        self.metadata = {
            "argv": self.command, "dtype": dtype, "model_id": self.config["model_id"],
            "model_revision": self.config["model_revision"],
            "tokenizer_revision": self.config.get("tokenizer_revision") or self.config["model_revision"],
            "vllm_version": version, "gpu_index": self.config["gpu_index"],
            "gpu_uuid": self.config.get("gpu_uuid"),
            "resolved_executable": str(Path(executable_path).resolve()) if executable_path else None,
            "version_identity_note": "vllm_version identifies the current Python distribution; executable version is not independently verified",
            "baseline_policy": (
                "engine_defaults_under_fixed_context_and_cache_policy"
                if self.config["use_engine_defaults"] else "explicit_whitelisted_configuration"),
            "requested_tuning_values": (None if self.config["use_engine_defaults"] else {
                name: self.config[name] for name in ("max_num_seqs", "max_num_batched_tokens",
                                                    "gpu_memory_utilization", "enable_chunked_prefill")}),
            "effective_tuning_values": None,
            "base_url": self.base_url, "kernel_backend_lines": [],
            "memory_footprint_lines": [], "identity_complete": False,
            "log": "engine.log", "owned_pid": None,
        }
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _port_free(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # Match the server's bind semantics: a completed prior engine can
            # leave TIME_WAIT connections without an active listener. This does
            # not permit sharing a port with a listening server (SO_REUSEPORT).
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", self.config["port"]))
            except OSError as exc:
                raise EngineError("Port is occupied; refusing to attach to or stop an existing server") from exc

    def _health(self) -> bool:
        if self._process is None or self._process.poll() is not None:
            return False
        request = urllib.request.Request(self.base_url + "/models", method="GET")
        try:
            with self._opener.open(request, timeout=min(3, self.config["request_timeout_s"])) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise EngineError("Local engine health response exceeded its size limit")
                payload = json.loads(raw)
                return (response.status == 200 and isinstance(payload, dict)
                        and isinstance(payload.get("data"), list)
                        and any(isinstance(row, dict) and row.get("id") == "servetune-glimmer"
                                for row in payload["data"]))
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def start(self):
        if self._started_once:
            raise EngineError("A managed engine cannot be restarted; use a fresh run directory")
        self._started_once = True
        self._port_free()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.artifact_dir / "engine.log"
        self._log = log_path.open("x", encoding="utf-8")
        environment = dict(os.environ)
        # Model downloads may use HF_TOKEN. Provider credentials are unnecessary
        # for local serving and are not forwarded to the engine subprocess.
        for name in list(environment):
            if name.endswith("_API_KEY") or name in {"MODEL_API_KEY", "META_API_KEY", "BASETEN_API_KEY"}:
                environment.pop(name, None)
        environment["CUDA_VISIBLE_DEVICES"] = self.config.get("gpu_uuid") or str(self.config["gpu_index"])
        environment["SERVETUNE_ENGINE_OWNER"] = self._owner_marker
        environment["PYTHONUNBUFFERED"] = "1"
        started = time.monotonic()
        try:
            self._process = subprocess.Popen(self.command, stdout=self._log, stderr=subprocess.STDOUT,
                                             env=environment, start_new_session=True)
            # start_new_session creates both a session and process group whose
            # ID is this child PID. This is never read from caller configuration.
            self._owned_pgid = self._process.pid
            self._owned_session = self._process.pid
            self.metadata["owned_pid"] = self._process.pid
            self.metadata["owned_process_group"] = self._owned_pgid
            self.metadata["cuda_visible_devices"] = environment["CUDA_VISIBLE_DEVICES"]
            while time.monotonic() - started < self.config["startup_timeout_s"]:
                if self._process.poll() is not None:
                    raise EngineError(f"Owned vLLM process exited during startup (code {self._process.returncode}); inspect engine.log")
                if self._health():
                    self.metadata["startup_seconds"] = time.monotonic() - started
                    self._read_log_metadata()
                    return self
                time.sleep(min(0.25, max(0.01, self.config["startup_timeout_s"] - (time.monotonic() - started))))
            raise EngineError("Owned vLLM process did not become healthy before the startup timeout")
        except BaseException:
            self.stop()
            raise

    def _read_log_metadata(self):
        if self._log is not None:
            self._log.flush()
        path = self.artifact_dir / "engine.log"
        if not path.exists():
            return
        # Bound inspection and avoid inferring a kernel from the requested dtype.
        with path.open(encoding="utf-8", errors="replace") as stream:
            content = stream.read(2_000_000)
        lines = content.splitlines()
        backend_terms = ("flashinfer", "flash_attn", "flash attention", "flashattention",
                         "cutlass", "marlin", "triton", "deepgemm", "humming",
                         "torch_sdpa", "flex_attention")
        backend = [line[:1000] for line in lines
                   if any(term in line.lower() for term in backend_terms)
                   and any(term in line.lower() for term in ("selected", "using", "backend"))]
        memory = [line[:1000] for line in lines
                  if any(term in line.lower() for term in
                         ("model loading took", "loading model weights took", "model weights take", "available kv cache memory", "gpu kv cache size", "memory footprint"))]
        self.metadata["kernel_backend_lines"] = backend[:50]
        self.metadata["memory_footprint_lines"] = memory[:50]
        self.metadata["identity_complete"] = bool(backend and memory and self.metadata["vllm_version"])
        self.metadata["identity_note"] = (
            "Startup logs retained; verify the exact linear and attention kernel paths from these lines"
            if backend else "Backend was not identified from startup logs; do not claim a kernel path")

    def _owned_group_state(self):
        """Return owned/absent/unverified, including after the leader exits.

        Linux workers inherit a random per-engine environment marker. Requiring
        that marker plus the original session ID avoids signalling a later,
        unrelated process group that recycled the old leader's numeric PID.
        On non-procfs platforms ownership is provable only while the original
        Popen child is still alive; otherwise cleanup fails closed.
        """
        if self._owned_pgid is None:
            return "absent"
        if self._proc_root.is_dir():
            members = []
            marker_found = False
            for path in self._proc_root.iterdir():
                if not path.name.isdigit():
                    continue
                try:
                    fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
                    if int(fields[2]) != self._owned_pgid or fields[0] == "Z":
                        continue
                    if int(fields[3]) != self._owned_session:
                        return "unverified"
                    members.append(int(path.name))
                    try:
                        marker = f"SERVETUNE_ENGINE_OWNER={self._owner_marker}".encode()
                        marker_found |= marker in (path / "environ").read_bytes().split(b"\0")
                    except OSError:
                        pass
                except (OSError, ValueError, IndexError):
                    continue  # A process may disappear during read-only inspection.
            if not members:
                return "absent"
            return "owned" if marker_found else "unverified"
        process = self._process
        if process is not None and process.poll() is None:
            try:
                if (os.getpgid(process.pid) == self._owned_pgid
                        and os.getsid(process.pid) == self._owned_session):
                    return "owned"
            except ProcessLookupError:
                return "absent"
        try:
            os.killpg(self._owned_pgid, 0)  # Existence query, never a termination signal.
        except ProcessLookupError:
            return "absent"
        return "unverified"

    def stop(self):
        process = self._process
        try:
            if process is not None:
                state = self._owned_group_state()
                if state == "unverified":
                    raise EngineError("Cannot prove ownership of remaining process group; refusing to signal it")
                if state == "owned":
                    try:
                        os.killpg(self._owned_pgid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    deadline = time.monotonic() + 10
                    while self._owned_group_state() == "owned" and time.monotonic() < deadline:
                        process.poll()  # Reap the leader without abandoning its workers.
                        time.sleep(0.05)
                    state = self._owned_group_state()
                    if state == "owned":
                        try:
                            os.killpg(self._owned_pgid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        kill_deadline = time.monotonic() + 5
                        while self._owned_group_state() == "owned" and time.monotonic() < kill_deadline:
                            process.poll()
                            time.sleep(0.05)
                        if self._owned_group_state() != "absent":
                            raise EngineError("Owned worker group did not disappear after forced cleanup")
                    elif state == "unverified":
                        raise EngineError("Process-group ownership changed during cleanup; refusing a further signal")
                if process.poll() is None:
                    process.wait(timeout=5)
                self.metadata["cleanup_status"] = "completed"
        except BaseException:
            self.metadata["cleanup_status"] = "failed"
            raise
        finally:
            if self._log is not None:
                self._read_log_metadata()
                self._log.close()
                self._log = None
            if process is not None:
                self.metadata["returncode"] = process.returncode

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        self.stop()
