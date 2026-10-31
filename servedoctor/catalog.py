"""ServeIncidents fault taxonomy, allowed actions and sealed answer keys.

The taxonomy is the label set every arm chooses from. Answer keys are written
separately from the public incident files so an agent can never read them.
"""
from __future__ import annotations

import math

ROOT_CAUSES = {
    "healthy": "No incident. Normal variation only.",
    "traffic_surge": "Offered request rate exceeds serving capacity.",
    "long_prompt_flood": "The prompt-length mix shifted toward long prompts; prefill dominates.",
    "kv_cache_starvation": "Too little GPU memory reserved for the KV cache for the workload.",
    "batch_limit_too_low": "The engine's concurrent sequence limit is too low for the offered load.",
    "context_limit_too_small": "The engine's maximum context length rejects valid requests.",
    "gpu_contention": "Another process on the same GPU competes for compute.",
    "underutilization": "Service is healthy, but the GPU draws high power while serving little traffic; an efficiency issue.",
    "other": "None of the above.",
}

INCIDENT_CAUSES = [c for c in ROOT_CAUSES if c not in ("healthy", "other")]

# Engine knobs an action may change, with hard bounds the executor enforces.
ENGINE_KNOBS = {
    "max_num_seqs": (int, 1, 1024),
    "max_num_batched_tokens": (int, 512, 65536),
    "gpu_memory_utilization": (float, 0.5, 0.95),
    "max_model_len": (int, 256, 32768),
}

ACTION_TYPES = {
    "no_action": "Leave the system unchanged.",
    "set_engine_config": "Restart the engine with ONE changed knob: {knob, value}. Knobs: "
                         + ", ".join(ENGINE_KNOBS) + ".",
    "gateway_rate_limit": "Admit at most {max_rps} requests per second at the gateway; excess requests are shed.",
    "gateway_max_prompt_tokens": "Reject requests whose prompt exceeds {max_prompt_tokens} tokens at the gateway.",
    "stop_gpu_process": "Stop the non-engine GPU process {pid} listed in the GPU process table.",
    "recommend_consolidation": "Advisory only: consolidate traffic onto fewer GPUs. No change is applied.",
    "escalate_to_human": "Page a human; no automated change.",
}

# Per root cause: which action types fix it (with an optional knob/direction),
# and which are harmful. Escalation is always safe but never a fix.
ANSWER_RULES = {
    "healthy": {"fix": [{"type": "no_action"}], "harmful": "any_change"},
    "traffic_surge": {"fix": [{"type": "gateway_rate_limit"}],
                      "harmful": [{"type": "set_engine_config", "knob": "max_num_seqs", "direction": "down"},
                                  {"type": "set_engine_config", "knob": "gpu_memory_utilization", "direction": "down"},
                                  {"type": "set_engine_config", "knob": "max_model_len", "direction": "down"}]},
    "long_prompt_flood": {"fix": [{"type": "gateway_max_prompt_tokens"}, {"type": "gateway_rate_limit"}],
                          "harmful": [{"type": "set_engine_config", "knob": "gpu_memory_utilization", "direction": "down"},
                                      {"type": "set_engine_config", "knob": "max_num_seqs", "direction": "down"}]},
    "kv_cache_starvation": {"fix": [{"type": "set_engine_config", "knob": "gpu_memory_utilization", "direction": "up"}],
                            "harmful": [{"type": "set_engine_config", "knob": "gpu_memory_utilization", "direction": "down"},
                                        {"type": "set_engine_config", "knob": "max_num_seqs", "direction": "up"}]},
    "batch_limit_too_low": {"fix": [{"type": "set_engine_config", "knob": "max_num_seqs", "direction": "up"}],
                            "harmful": [{"type": "set_engine_config", "knob": "max_num_seqs", "direction": "down"},
                                        {"type": "gateway_rate_limit"}]},
    "context_limit_too_small": {"fix": [{"type": "set_engine_config", "knob": "max_model_len", "direction": "up"}],
                                "harmful": [{"type": "set_engine_config", "knob": "max_model_len", "direction": "down"}]},
    "gpu_contention": {"fix": [{"type": "stop_gpu_process"}],
                       "harmful": [{"type": "set_engine_config", "knob": "gpu_memory_utilization", "direction": "down"}]},
    "underutilization": {"fix": [{"type": "recommend_consolidation"}], "harmful": "any_change"},
}


class ActionError(ValueError):
    pass


def validate_action(action, *, current_config=None):
    """Return a normalized action or raise ActionError. Never executes anything."""
    if type(action) is not dict or type(action.get("type")) is not str:
        raise ActionError("Action must be an object with a string type")
    kind = action["type"]
    if kind not in ACTION_TYPES:
        raise ActionError(f"Unknown action type {kind!r}")
    allowed = {"no_action": {"type"}, "recommend_consolidation": {"type"},
               "escalate_to_human": {"type"},
               "set_engine_config": {"type", "knob", "value"},
               "gateway_rate_limit": {"type", "max_rps"},
               "gateway_max_prompt_tokens": {"type", "max_prompt_tokens"},
               "stop_gpu_process": {"type", "pid"}}[kind]
    if set(action) != allowed:
        raise ActionError(f"{kind} requires exactly the fields {sorted(allowed)}")
    if kind == "set_engine_config":
        knob = action["knob"]
        if knob not in ENGINE_KNOBS:
            raise ActionError(f"Knob {knob!r} is not whitelisted")
        kind_type, low, high = ENGINE_KNOBS[knob]
        value = action["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ActionError("Knob value must be a finite number")
        if kind_type is int:
            if int(value) != value:
                raise ActionError(f"{knob} must be an integer")
            value = int(value)
        else:
            value = round(float(value), 4)
        if not low <= value <= high:
            raise ActionError(f"{knob} must be in [{low}, {high}]")
        if current_config is not None and current_config.get(knob) == value:
            raise ActionError(f"{knob} is already {value}")
        return {"type": kind, "knob": knob, "value": value}
    if kind == "gateway_rate_limit":
        value = action["max_rps"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.1 <= value <= 1000:
            raise ActionError("max_rps must be in [0.1, 1000]")
        return {"type": kind, "max_rps": round(float(value), 3)}
    if kind == "gateway_max_prompt_tokens":
        value = action["max_prompt_tokens"]
        if type(value) is not int or not 64 <= value <= 32768:
            raise ActionError("max_prompt_tokens must be an integer in [64, 32768]")
        return {"type": kind, "max_prompt_tokens": value}
    if kind == "stop_gpu_process":
        if type(action["pid"]) is not int or action["pid"] <= 1:
            raise ActionError("pid must be a positive integer")
        return {"type": kind, "pid": action["pid"]}
    return {"type": kind}


def _matches(rule, action, current_config):
    if rule["type"] != action["type"]:
        return False
    if "knob" in rule and rule["knob"] != action.get("knob"):
        return False
    if "direction" in rule:
        before = (current_config or {}).get(action["knob"])
        if before is None:
            return False
        if rule["direction"] == "up" and not action["value"] > before:
            return False
        if rule["direction"] == "down" and not action["value"] < before:
            return False
    return True


def judge_actions(root_cause, actions, *, current_config, contention_pids=()):
    """Score proposed actions against the sealed rules for the true root cause.

    Returns fixes (an action matches a fix rule), harmful (any action matches a
    harmful rule, or changes anything when the truth requires no change), and
    a per-action breakdown.
    """
    rules = ANSWER_RULES[root_cause]
    change_types = {"set_engine_config", "gateway_rate_limit", "gateway_max_prompt_tokens", "stop_gpu_process"}
    detail, fixes, harmful = [], False, False
    for action in actions:
        is_fix = any(_matches(rule, action, current_config) for rule in rules["fix"])
        if is_fix and action["type"] == "stop_gpu_process" and action["pid"] not in contention_pids:
            is_fix = False
        if rules["harmful"] == "any_change":
            is_harm = action["type"] in change_types
        else:
            is_harm = any(_matches(rule, action, current_config) for rule in rules["harmful"])
        if action["type"] == "stop_gpu_process" and action["pid"] not in contention_pids:
            is_harm = True  # Stopping anything other than the offending job is never acceptable.
        fixes |= is_fix
        harmful |= is_harm
        detail.append({"action": action, "fix": is_fix, "harmful": is_harm})
    return {"fixes": fixes, "harmful": harmful, "detail": detail}
