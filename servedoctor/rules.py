"""A transparent threshold baseline. Thresholds may be tuned on dev incidents only.

It sees exactly the same observation as the model arms. It is written by the
people who designed the faults, so it is an optimistic baseline, not a strawman.
"""
from __future__ import annotations

ENGINE_KNOBS = ("max_num_seqs", "gpu_memory_utilization", "max_model_len", "max_num_batched_tokens")

THRESHOLDS = {
    "window_buckets": 3,
    "context_error_rate": 0.01,
    "surge_arrival_ratio": 1.2,
    "long_prompt_ratio": 2.0,
    "contention_throughput_ratio": 0.85,
    "latency_slo_fraction": 1.0,
    "waiting_floor": 5,
    "kv_pressure_pct": 90,
    "underutil_arrival_ratio": 0.35,
    "rate_limit_ratio": 1.6,
}


def _avg(rows, field):
    values = [r[field] for r in rows if r.get(field) is not None]
    return sum(values) / len(values) if values else None


def decide(observation, thresholds=THRESHOLDS):
    rows = observation["recent_10s_buckets"][-thresholds["window_buckets"]:]
    profile = observation.get("normal_profile") or {}
    config = observation["engine_config"]
    reference = observation.get("reference_engine_config") or {}
    if not rows:
        return {"incident": False, "root_cause": "healthy", "actions": [{"type": "no_action"}]}
    slo = observation["slo"]
    arrivals = _avg(rows, "arrivals_rps") or 0.0
    admitted = max(1.0, sum((r["arrivals_rps"] - r["shed_rps"]) * 10 for r in rows))
    status_400 = sum(r["errors"].get("http_400", 0) for r in rows)
    p95 = max([r["p95_latency_s"] for r in rows if r.get("p95_latency_s") is not None] or [0])
    waiting = max(r["waiting_max"] for r in rows)
    kv = max(r["kv_usage_pct_max"] or 0 for r in rows)
    preempt = _avg(rows, "preemptions_per_s") or 0
    prompt_mean = _avg(rows, "prompt_tokens_mean")
    gen = _avg(rows, "gen_tokens_per_s")
    running = _avg(rows, "running") or 0
    ref_arrivals = profile.get("arrivals_rps")
    ref_prompt = profile.get("prompt_tokens_mean")
    ref_gen = profile.get("gen_tokens_per_s")
    changed = {k for k in ENGINE_KNOBS if reference.get(k) is not None and config.get(k) != reference.get(k)}

    def revert(knob, cause):
        return {"incident": True, "root_cause": cause,
                "actions": [{"type": "set_engine_config", "knob": knob, "value": reference[knob]}]}

    if status_400 / admitted > thresholds["context_error_rate"]:
        if "max_model_len" in changed:
            return revert("max_model_len", "context_limit_too_small")
        return {"incident": True, "root_cause": "context_limit_too_small", "actions": [{"type": "escalate_to_human"}]}
    foreign = [p for p in observation.get("gpu_processes", [])
               if "vllm" not in (p.get("command") or "") and "EngineCore" not in (p.get("command") or "")]
    stressed = p95 > slo["p95_latency_s"] * thresholds["latency_slo_fraction"] or waiting >= thresholds["waiting_floor"]
    if foreign and ref_gen and gen is not None and (gen < thresholds["contention_throughput_ratio"] * ref_gen or stressed):
        return {"incident": True, "root_cause": "gpu_contention",
                "actions": [{"type": "stop_gpu_process", "pid": foreign[0]["pid"]}]}
    if stressed:
        long_prompts = ref_prompt and prompt_mean and prompt_mean > thresholds["long_prompt_ratio"] * ref_prompt
        if long_prompts:
            return {"incident": True, "root_cause": "long_prompt_flood",
                    "actions": [{"type": "gateway_max_prompt_tokens", "max_prompt_tokens": int(max(256, 2 * ref_prompt))}]}
        if ref_arrivals and arrivals > thresholds["surge_arrival_ratio"] * ref_arrivals:
            return {"incident": True, "root_cause": "traffic_surge",
                    "actions": [{"type": "gateway_rate_limit",
                                 "max_rps": round(thresholds["rate_limit_ratio"] * ref_arrivals, 2)}]}
        if "max_num_seqs" in changed and running >= config["max_num_seqs"] - 0.5:
            return revert("max_num_seqs", "batch_limit_too_low")
        if "gpu_memory_utilization" in changed and (kv >= thresholds["kv_pressure_pct"] or preempt > 0):
            return revert("gpu_memory_utilization", "kv_cache_starvation")
        return {"incident": True, "root_cause": "other", "actions": [{"type": "escalate_to_human"}]}
    if ref_arrivals and arrivals < thresholds["underutil_arrival_ratio"] * ref_arrivals:
        return {"incident": True, "root_cause": "underutilization", "actions": [{"type": "recommend_consolidation"}]}
    return {"incident": False, "root_cause": "healthy", "actions": [{"type": "no_action"}]}
