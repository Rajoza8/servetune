"""Frozen preflight protocol. No arbitrary engine flags or executable commands."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re

from .artifacts import digest


DEFAULT = {
    "schema_version": 1,
    "engine": {
        "model_id": "meta-models/Muse-Glimmer-30B", "model_revision": None,
        "host": "127.0.0.1", "port": 8000, "engine_executable": "vllm",
        "startup_timeout_s": 600, "request_timeout_s": 120, "gpu_index": 0,
        "max_model_len": 4096, "max_num_seqs": 8, "max_num_batched_tokens": 4096,
        "gpu_memory_utilization": 0.9, "enable_chunked_prefill": True,
        "use_engine_defaults": True,
        "enable_prefix_caching": False, "fp8_quantization": "fp8_per_tensor",
    },
    "trace": {"seed": 20261030, "duration_s": 120.0, "arrival_rate": 0.1,
              "max_output_tokens": 128, "max_requests": 256},
    "measurement": {"repeats": 3, "cv_limit": 0.03, "warmup_requests": 1,
                    "idle_seconds": 3.0, "allow_power_fallback": False,
                    "max_counter_relative_error": 0.01},
    "try_fp8": True,
    "data": {"prompts": None, "dev": None, "final": None, "provenance": None},
    "quality": {"dev_items": 150, "final_items": 300, "dev_allowed_decrease": 3,
                "final_allowed_decrease": 6, "max_output_tokens": 1024,
                "wording": "within the predeclared 2-percentage-point tolerance"},
    "provider_caps_usd": {"meta": 15, "baseten": 5},
}


def _positive(value, name, *, integer=False, zero=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite {'integer' if integer else 'number'}")
    if value < 0 or (not zero and value == 0):
        raise ValueError(f"{name} must be {'nonnegative' if zero else 'positive'}")


def load_config(path):
    value = json.loads(Path(path).read_text())
    validate(value)
    return value


def validate(value):
    if type(value) is not dict or set(value) != set(DEFAULT) or value["schema_version"] != 1:
        raise ValueError("Configuration must have the exact version-1 fields")
    for section in ("engine", "trace", "measurement", "data", "quality"):
        if type(value[section]) is not dict or set(value[section]) != set(DEFAULT[section]):
            raise ValueError(f"Unexpected or missing {section} fields")
    if value["provider_caps_usd"] != {"meta": 15, "baseten": 5}:
        raise ValueError("This authorization is capped at $15 Meta / $5 Baseten")
    e, t, m = value["engine"], value["trace"], value["measurement"]
    if e["model_id"] != DEFAULT["engine"]["model_id"] or e["engine_executable"] != "vllm":
        raise ValueError("Preflight only launches the fixed vLLM Glimmer command")
    if e["model_revision"] is not None and not re.fullmatch(r"[0-9a-f]{40}", e["model_revision"]):
        raise ValueError("model_revision must be an immutable 40-character commit or null before setup")
    if e["host"] != "127.0.0.1":
        raise ValueError("The preflight server must bind to loopback")
    for field in ("port", "startup_timeout_s", "request_timeout_s", "max_model_len", "max_num_seqs", "max_num_batched_tokens"):
        _positive(e[field], field, integer=True)
    _positive(e["gpu_index"], "gpu_index", integer=True, zero=True)
    if not 1024 <= e["port"] <= 65535 or e["gpu_index"] != 0:
        raise ValueError("Use an unprivileged port and the sole GPU, index 0")
    _positive(e["gpu_memory_utilization"], "gpu_memory_utilization")
    if not e["gpu_memory_utilization"] <= 0.95:
        raise ValueError("GPU memory utilization must not exceed 0.95")
    for field in ("enable_chunked_prefill", "enable_prefix_caching", "use_engine_defaults"):
        if type(e[field]) is not bool:
            raise ValueError(f"{field} must be boolean")
    if e["fp8_quantization"] != "fp8_per_tensor":
        raise ValueError("The online FP8 path is fp8_per_tensor; pin and verify its actual backend")
    for field in ("duration_s", "arrival_rate"):
        _positive(t[field], field)
    for field in ("max_output_tokens", "max_requests"):
        _positive(t[field], field, integer=True)
    if type(t["seed"]) is not int or t["max_requests"] > 256 or t["max_output_tokens"] > 4096:
        raise ValueError("Trace seed must be integer; max 256 requests and 4096 output tokens")
    if t["duration_s"] < 120:
        raise ValueError("Live arrival traces must span at least 120 seconds")
    if t["max_output_tokens"] >= e["max_model_len"]:
        raise ValueError("Output token cap must leave space for the prompt")
    if m["repeats"] != 3 or m["cv_limit"] != 0.03 or m["max_counter_relative_error"] != 0.01:
        raise ValueError("The preflight noise protocol is three runs, CV <3%, counter error <1%")
    _positive(m["idle_seconds"], "idle_seconds")
    _positive(m["warmup_requests"], "warmup_requests", integer=True)
    if type(m["allow_power_fallback"]) is not bool or type(value["try_fp8"]) is not bool:
        raise ValueError("Flags must be boolean")
    if value["quality"] != DEFAULT["quality"]:
        raise ValueError("The authorized v4 quality protocol is frozen at 150/300 items and 3/6 losses")
    for name, path in value["data"].items():
        if path is not None and (type(path) is not str or not path):
            raise ValueError(f"data.{name} must be a path or null")
    return value


def config_hash(value):
    return digest(validate(value))
