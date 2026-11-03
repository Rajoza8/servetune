"""Frozen v4 search space, complete-repeat summaries, and common decisions.

The caller freezes the returned configuration before any study measurements.
Spark changes exactly one knob. Random search draws uniformly from the full
finite space, excluding only the current configuration, and may change several.
"""

from __future__ import annotations

from copy import deepcopy
import math
import statistics


KNOBS = ("max_num_seqs", "max_num_batched_tokens", "enable_chunked_prefill", "gpu_memory_utilization")
DEFAULT_STUDY = {
    "schema_version": 1,
    "calibration": {"rates": [.1, .5, 1., 2., 4., 8.], "duration_s": 120., "max_requests": 4096},
    "map": {"duration_s": 480., "load_fractions": [.25, .5, .8],
            "max_num_seqs": [64], "repeats": 3},
    "workload": {"seed": 20261030, "max_output_tokens": 128, "max_requests": 16384,
                 "warmup_requests": 1},
    "tuning": {"arm_budget_s": 21600, "seed": 20261030, "max_trials": 24,
               "slo_s": 15., "trial_estimate_s": 4200},
    "confirmation": {"repeats": 5},
    "space": {
        "max_num_seqs": [8, 16, 32, 64, 128, 256, 512, 1024],
        "max_num_batched_tokens": [2048, 4096, 8192, 16384],
        "enable_chunked_prefill": [False, True],
        "gpu_memory_utilization": [.7, .8, .85, .9, .92],
    },
}


def _number(value, label, *, lower=0, upper=float("inf"), inclusive_lower=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or (value < lower if inclusive_lower else value <= lower) or value > upper):
        raise ValueError(f"{label} must be a finite number within its declared bounds")
    return value


def _integer(value, label, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{label} must be an integer in [{lower}, {upper}]")
    return value


def _valid_knob_value(key, value):
    if key == "enable_chunked_prefill":
        return type(value) is bool
    if key == "max_num_seqs":
        return type(value) is int and 1 <= value <= 1024
    if key == "max_num_batched_tokens":
        return type(value) is int and 32 <= value <= 131072
    return (type(value) in (int, float) and math.isfinite(value) and .1 <= value <= .95)


def _member(key, value, values):
    return _valid_knob_value(key, value) and any(
        value == option and (key == "gpu_memory_utilization" or type(value) is type(option))
        for option in values)


def validate_space(space):
    if type(space) is not dict or set(space) != set(KNOBS):
        raise ValueError("Space must name exactly the four whitelisted knobs")
    for key in KNOBS:
        values = space[key]
        if type(values) is not list or not 1 <= len(values) <= 64:
            raise ValueError("Each knob space must be a nonempty finite list of at most 64 values")
        seen = []
        for value in values:
            if not _valid_knob_value(key, value) or _member(key, value, seen):
                raise ValueError(f"Invalid or duplicate value in space.{key}")
            seen.append(value)
    return space


def validate_knobs(knobs, space):
    validate_space(space)
    if type(knobs) is not dict or set(knobs) != set(KNOBS):
        raise ValueError("Configuration must contain exactly the four whitelisted knobs")
    if any(not _member(key, knobs[key], space[key]) for key in KNOBS):
        raise ValueError("Configuration is outside the frozen finite search space")
    return deepcopy(knobs)


def validate_study(config):
    if type(config) is not dict or set(config) != set(DEFAULT_STUDY) or type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        raise ValueError("Study config must have the exact version-1 fields")
    for key in ("calibration", "map", "workload", "tuning", "confirmation"):
        if type(config[key]) is not dict or set(config[key]) != set(DEFAULT_STUDY[key]):
            raise ValueError(f"Unexpected or missing study.{key} fields")
    validate_space(config["space"])
    calibration, grid, workload, tuning = [config[key] for key in ("calibration", "map", "workload", "tuning")]
    for name, section in (("calibration", calibration), ("map", grid)):
        _number(section["duration_s"], f"{name}.duration_s", lower=120, upper=3600, inclusive_lower=True)
    rates = calibration["rates"]
    if type(rates) is not list or not 1 <= len(rates) <= 16:
        raise ValueError("Predeclare 1–16 calibration rates")
    for rate in rates:
        _number(rate, "calibration rate", upper=1000)
    if rates != sorted(set(rates)):
        raise ValueError("Calibration rates must be unique and increasing")
    _integer(calibration["max_requests"], "calibration.max_requests", 1, 4096)
    fractions = grid["load_fractions"]
    if type(fractions) is not list or not 1 <= len(fractions) <= 8:
        raise ValueError("Predeclare a finite set of load fractions")
    for fraction in fractions:
        _number(fraction, "map load fraction", upper=.99)
    if fractions != sorted(set(fractions)):
        raise ValueError("Map load fractions must be unique and increasing")
    if type(grid["max_num_seqs"]) is not list or not grid["max_num_seqs"]:
        raise ValueError("Map sequence settings must be a nonempty list")
    if (any(not _member("max_num_seqs", value, config["space"]["max_num_seqs"])
            for value in grid["max_num_seqs"])
            or len(set(grid["max_num_seqs"])) != len(grid["max_num_seqs"])):
        raise ValueError("Map sequence settings must be unique values from the frozen space")
    if type(grid["repeats"]) is not int or grid["repeats"] != 3:
        raise ValueError("Map and tuning points require three measured repeats")
    if type(config["confirmation"]["repeats"]) is not int or config["confirmation"]["repeats"] < 5:
        raise ValueError("Final confirmation requires at least five repeats per configuration")
    if config["confirmation"]["repeats"] > 20:
        raise ValueError("Confirmation repeat count exceeds the bounded study protocol")
    _integer(workload["seed"], "workload.seed", 0, 2**63 - 1)
    _integer(workload["max_output_tokens"], "workload.max_output_tokens", 1, 4096)
    _integer(workload["max_requests"], "workload.max_requests", 1, 16384)
    _integer(workload["warmup_requests"], "workload.warmup_requests", 1, 16)
    _integer(tuning["seed"], "tuning.seed", 0, 2**63 - 1)
    _integer(tuning["max_trials"], "tuning.max_trials", 1, 24)
    _number(tuning["arm_budget_s"], "tuning.arm_budget_s", upper=21600)
    _number(tuning["slo_s"], "tuning.slo_s", upper=600)
    _number(tuning["trial_estimate_s"], "tuning.trial_estimate_s", upper=21600)
    return deepcopy(config)


def apply_proposal(current, proposal, space):
    current = validate_knobs(current, space)
    if type(proposal) is not dict or set(proposal) != {"hypothesis", "expected_effect", "diff"}:
        raise ValueError("Spark proposal requires exactly hypothesis, expected_effect, and diff")
    for key in ("hypothesis", "expected_effect"):
        if type(proposal[key]) is not str or not 1 <= len(proposal[key].strip()) <= 1000:
            raise ValueError("Proposal explanations must contain 1–1000 characters")
    diff = proposal["diff"]
    if type(diff) is not dict or len(diff) != 1 or not set(diff) <= set(KNOBS):
        raise ValueError("Spark must change exactly one whitelisted knob")
    updated = validate_knobs({**current, **diff}, space)
    if updated == current:
        raise ValueError("Proposal must actually change the current configuration")
    return updated


def random_proposal(current, space, rng):
    current = validate_knobs(current, space)
    # Mixed-radix indexing draws uniformly from all configurations except the
    # current one, without a retry loop or materializing a large product grid.
    size, current_index = 1, 0
    for key in KNOBS:
        current_index = current_index * len(space[key]) + next(
            index for index, value in enumerate(space[key]) if value == current[key])
        size *= len(space[key])
    if size < 2:
        raise ValueError("Random search requires at least one alternative configuration")
    selected = rng.randrange(size - 1)
    if selected >= current_index:
        selected += 1
    config = {}
    for key in reversed(KNOBS):
        selected, offset = divmod(selected, len(space[key]))
        config[key] = space[key][offset]
    config = {key: config[key] for key in KNOBS}
    return {"config": config, "diff": {key: value for key, value in config.items() if value != current[key]},
            "hypothesis": "Uniform random configuration from the same frozen finite space, excluding the current configuration",
            "expected_effect": "Unmeasured; the same energy, latency, completeness, and quality gates apply"}


def _finite_positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def summarize_repeats(runs, expected_repeats=3):
    _integer(expected_repeats, "expected_repeats", 3, 20)
    if type(runs) is not list:
        raise ValueError("Measured repeats must be a list")
    required = ("joules_per_output_token", "joules_per_completed_request", "p95_latency_s",
                "generated_tokens", "completed_requests")
    reasons = []
    if len(runs) != expected_repeats:
        reasons.append("missing_or_extra_repeats")
    if any(type(run) is not dict or run.get("status") != "pass"
           or run.get("all_requests_completed") is not True for run in runs):
        reasons.append("incomplete_or_failed_workload")
    if not runs or any(any(not _finite_positive(run.get(key)) for key in required)
                       for run in runs if type(run) is dict):
        reasons.append("missing_or_invalid_metrics")
    trace_hashes = {run.get("trace_sha256") for run in runs if type(run) is dict}
    if len(trace_hashes) != 1 or (None in trace_hashes and any("trace_sha256" in run for run in runs if type(run) is dict)):
        reasons.append("repeat_trace_mismatch")
    result = {"status": "fail" if reasons else "pass", "all_requests_completed": not reasons,
              "repeats": len(runs), "expected_repeats": expected_repeats, "reasons": reasons,
              "trace_sha256": next(iter(trace_hashes)) if len(trace_hashes) == 1 else None,
              "aggregation": "median across all required measured repeats; failures never dropped"}
    for key in (*required, "joules", "duration_s", "output_tokens_per_second", "p50_latency_s",
                "p50_ttft_s", "p95_ttft_s"):
        values = [run.get(key) for run in runs if type(run) is dict]
        complete = len(values) == expected_repeats and all(_finite_positive(value) for value in values)
        result[key] = statistics.median(values) if complete else None
        result[key + "_min"] = min(values) if complete else None
        result[key + "_max"] = max(values) if complete else None
    for field, metric in (("joules_per_token_cv", "joules_per_output_token"),
                          ("p95_latency_cv", "p95_latency_s")):
        values = [run.get(metric) for run in runs if type(run) is dict]
        result[field] = (statistics.stdev(values) / statistics.mean(values)
                         if len(values) == expected_repeats and all(_finite_positive(value) for value in values)
                         else None)
    return result


def acceptance(candidate_summary, incumbent_summary, baseline_summary, quality_gate, *, slo_s, observed_cv):
    _number(slo_s, "slo_s")
    _number(observed_cv, "observed_cv", inclusive_lower=True)
    threshold = max(2 * observed_cv, .02)
    reasons = []
    summaries = (candidate_summary, incumbent_summary, baseline_summary)
    required = ("joules_per_output_token", "joules_per_completed_request", "p95_latency_s",
                "generated_tokens", "completed_requests")
    valid = all(type(row) is dict and row.get("status") == "pass"
                and row.get("all_requests_completed") is True
                and all(_finite_positive(row.get(key)) for key in required) for row in summaries)
    if not valid:
        reasons.append("incomplete_or_invalid_measurements")
    if type(quality_gate) is not dict or quality_gate.get("passed") is not True:
        reasons.append("quality_gate_failed")
    improvement, drift = None, None
    if valid:
        if candidate_summary["p95_latency_s"] > slo_s:
            reasons.append("latency_slo_exceeded")
        hashes = [row.get("trace_sha256") for row in summaries]
        if any(value is not None for value in hashes) and (None in hashes or len(set(hashes)) != 1):
            reasons.append("frozen_trace_mismatch")
        if candidate_summary["completed_requests"] != baseline_summary["completed_requests"]:
            reasons.append("completed_request_count_changed")
        improvement = ((incumbent_summary["joules_per_output_token"] - candidate_summary["joules_per_output_token"])
                       / incumbent_summary["joules_per_output_token"])
        if improvement <= threshold:
            reasons.append("insufficient_energy_improvement")
        fraction = abs(candidate_summary["generated_tokens"] - baseline_summary["generated_tokens"]) / baseline_summary["generated_tokens"]
        both = (candidate_summary["joules_per_output_token"] < baseline_summary["joules_per_output_token"]
                and candidate_summary["joules_per_completed_request"] < baseline_summary["joules_per_completed_request"])
        drift = {"fraction": fraction, "flagged": fraction > .02, "eligible": fraction <= .02 or both,
                 "reference": "same_shared_baseline"}
        if not drift["eligible"]:
            reasons.append("length_drift_without_both_energy_gains")
    return {"accepted": not reasons, "status": "accepted" if not reasons else "rejected",
            "reasons": reasons, "improvement_fraction": improvement,
            "required_improvement_fraction": threshold, "length_drift": drift,
            "slo_s": slo_s, "observed_cv": observed_cv,
            "quality_wording": quality_gate.get("wording") if isinstance(quality_gate, dict) else None,
            "rule": "strict median J/token gain over incumbent; shared-baseline length check; complete workload, SLO, and frozen quality gate"}
