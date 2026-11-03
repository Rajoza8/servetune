"""Build what an operator could see at time t, with no look-ahead.

Observations are computed only from telemetry rows, change-log events and log
lines stamped at or before `now`. The same observation feeds every arm.
"""
from __future__ import annotations

import json
from pathlib import Path

from servetune.workload import percentile

from .telemetry import read_jsonl

BUCKET_S = 10
WINDOW_BUCKETS = 18


def load_incident(path):
    root = Path(path)
    recording = json.loads((root / "recording.json").read_text())
    if recording.get("status") == "failed":
        raise ValueError("Failed recording cannot be evaluated; retain it and record in a new directory")
    return {"id": root.name, "telemetry": read_jsonl(root / "telemetry.jsonl"),
            "events": json.loads((root / "events.json").read_text()),
            "engine_config": json.loads((root / "engine_config.json").read_text()),
            "slo": json.loads((root / "slo.json").read_text()),
            "recording": recording}


def _bucket(rows, previous):
    client = [r.get("client") or {} for r in rows]
    vllm = [r.get("vllm") or {} for r in rows]
    gpu = [r.get("gpu") or {} for r in rows]
    span = max(1e-9, rows[-1]["t"] - (previous["t"] if previous else rows[0]["t"] - 1))
    lat = [x for c in client for x in c.get("latencies_s", [])]
    ttft = [x for c in client for x in c.get("ttfts_s", [])]
    errors = {}
    for c in client:
        for k, v in (c.get("errors") or {}).items():
            errors[k] = errors.get(k, 0) + v
    arrivals = sum(c.get("arrivals", 0) for c in client)
    prompt_means = [(c["arrival_prompt_tokens_est_mean"], c["arrivals"]) for c in client
                    if c.get("arrival_prompt_tokens_est_mean") is not None]

    def delta(field):
        first = (previous or {}).get("vllm", {}).get(field) if previous else None
        last = next((v.get(field) for v in reversed(vllm) if field in v), None)
        if first is None:
            first = next((v.get(field) for v in vllm if field in v), None)
        if first is None or last is None:
            return None
        return max(0.0, last - first) / span

    def mean(values):
        values = [v for v in values if isinstance(v, (int, float))]
        return round(sum(values) / len(values), 2) if values else None

    return {
        "t_end": round(rows[-1]["t"], 1),
        "arrivals_rps": round(arrivals / span, 2),
        "shed_rps": round(sum(c.get("shed", 0) for c in client) / span, 2),
        "ok_rps": round(sum(c.get("completed_ok", 0) for c in client) / span, 2),
        "errors": errors,
        "p50_latency_s": _round(percentile(lat, 0.5)),
        "p95_latency_s": _round(percentile(lat, 0.95)),
        "p95_ttft_s": _round(percentile(ttft, 0.95)),
        "prompt_tokens_mean": (round(sum(m * n for m, n in prompt_means) / sum(n for _, n in prompt_means))
                               if prompt_means else None),
        "running": mean([v.get("running") for v in vllm]),
        "waiting_max": max([v.get("waiting", 0) for v in vllm] or [0]),
        "kv_usage_pct_max": _round(max([v.get("kv_usage", 0) for v in vllm] or [0])),
        "preemptions_per_s": _round(delta("preemptions_total")),
        "gen_tokens_per_s": _round(delta("generation_tokens_total")),
        "prompt_tokens_per_s": _round(delta("prompt_tokens_total")),
        "gpu_power_w": mean([g.get("power_w") for g in gpu]),
        "gpu_util_pct": mean([g.get("util_gpu") for g in gpu]),
        "gpu_mem_used_mb": mean([g.get("mem_used_mb") for g in gpu]),
    }


def _round(value, digits=2):
    return None if value is None else round(value, digits)


def buckets(rows, now, size=BUCKET_S):
    visible = [r for r in rows if r["t"] <= now]
    out, current, previous, edge = [], [], None, size
    for row in visible:
        while row["t"] > edge:
            if current:
                out.append(_bucket(current, previous))
                previous = current[-1]
            current, edge = [], edge + size
        current.append(row)
    if current:
        out.append(_bucket(current, previous))
    return out


def normal_profile(reference_rows):
    """Median-style summary of a healthy reference recording."""
    if not reference_rows:
        return None
    series = buckets(reference_rows, float("inf"))[1:] or buckets(reference_rows, float("inf"))

    def middle(field):
        values = sorted(b[field] for b in series if b.get(field) is not None)
        return values[len(values) // 2] if values else None

    return {field: middle(field) for field in (
        "arrivals_rps", "p95_latency_s", "p95_ttft_s", "prompt_tokens_mean", "running", "waiting_max",
        "kv_usage_pct_max", "gen_tokens_per_s", "gpu_power_w", "gpu_util_pct", "gpu_mem_used_mb")}


def observe(incident, now, *, profile=None, reference_config=None):
    rows = incident["telemetry"]
    visible = [r for r in rows if r["t"] <= now]
    series = buckets(rows, now)[-WINDOW_BUCKETS:]
    latest = visible[-1] if visible else {}
    processes = (latest.get("gpu") or {}).get("processes", [])
    log_lines = []
    for row in visible:
        if row["t"] >= now - 120:
            for line in row.get("log") or []:
                if line not in log_lines:
                    log_lines.append(line)
    return {
        "now_s": round(now, 1),
        "slo": incident["slo"],
        "engine_config": incident["engine_config"],
        "reference_engine_config": reference_config,
        "gateway_policy": latest.get("gateway"),
        "change_log": [e for e in incident["events"] if e["t"] <= now],
        "normal_profile": profile,
        "recent_10s_buckets": series,
        "gpu_processes": processes,
        "engine_log_recent": log_lines[-15:],
    }


TABLE_FIELDS = ["t_end", "arrivals_rps", "shed_rps", "ok_rps", "errors", "p50_latency_s", "p95_latency_s",
                "p95_ttft_s", "prompt_tokens_mean", "running", "waiting_max", "kv_usage_pct_max",
                "preemptions_per_s", "gen_tokens_per_s", "prompt_tokens_per_s", "gpu_power_w",
                "gpu_util_pct", "gpu_mem_used_mb"]


def render(observation):
    """Compact text for model prompts: a header JSON plus a CSV-like bucket table."""
    header = {k: v for k, v in observation.items() if k != "recent_10s_buckets"}
    lines = [json.dumps(header, separators=(",", ":"))]
    lines.append("recent_10s_buckets:")
    lines.append("|".join(TABLE_FIELDS))
    for row in observation["recent_10s_buckets"]:
        cells = []
        for field in TABLE_FIELDS:
            value = row.get(field)
            if field == "errors":
                value = ";".join(f"{k}={v}" for k, v in sorted(value.items())) if value else "-"
            cells.append("-" if value is None else str(value))
        lines.append("|".join(cells))
    return "\n".join(lines)
