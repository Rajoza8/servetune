"""ServeIncidents-Hard: compound faults, decoy GPU jobs, noisy change logs and
near-threshold severities.

v0 was saturated: three arms scored perfectly, partly because a deploy diff
named the faulty knob and every fault was single and strong. The Hard set keeps
the same recorder, observation, prompts, rules and models, and changes only the
incidents:

- every deploy changes one or two harmless engine knobs, so a config
  difference is no longer evidence by itself;
- harmless neighbouring GPU jobs ("decoys") appear in the process table, and
  every job, decoy or culprit, gets a random ordinary name;
- compound incidents have two simultaneous causes; at most two actions are
  allowed, so a complete fix must address both;
- severities sit just above the SLO line, as measured from v0 telemetry;
- irrelevant alerts and a plausible-looking change shortly before onset act as
  red herrings.

Nothing is tuned on the Hard set. It has no dev split: every arm runs exactly
as frozen for v0.
"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

from servetune.artifacts import digest

from .catalog import ROOT_CAUSES
from .record import JOB_MODULES
from .scenarios import BENIGN_CONFIG_DIFFS, BENIGN_EVENTS, _phase

# Harmless values for each engine knob at the base workload (base config is 64 /
# 8192 / 4096 / 0.9). None of these can cause an SLO breach on their own.
BENIGN_KNOBS = {"max_num_seqs": 96, "max_num_batched_tokens": 12288, "max_model_len": 6144,
                "gpu_memory_utilization": 0.86}
CONFIG_FAULT_KNOBS = {"kv_cache_starvation": "gpu_memory_utilization", "batch_limit_too_low": "max_num_seqs",
                      "context_limit_too_small": "max_model_len"}
RUNTIME_FAULTS = ("traffic_surge", "long_prompt_flood", "gpu_contention")
# Knobs that are not harmless next to a fault (more sequences or longer contexts
# deepen KV-cache starvation), so they are never used as benign noise with it.
INTERACTING_KNOBS = {"kv_cache_starvation": {"max_num_seqs", "max_model_len"}}

NOISE_ALERTS = [
    "Disk usage on /var/log reached 81% on the serving host (warning, non-paging).",
    "TLS certificate for the internal gateway expires in 21 days.",
    "NTP offset 12 ms on the serving host (threshold 50 ms).",
    "Prometheus remote-write queue lag 30 s (non-paging).",
    "Host CPU temperature 71 C (threshold 85 C).",
    "One synthetic probe from a remote region timed out (single occurrence).",
]
HERRING_CHANGES = [
    "Client SDK 2.4 rolled out to 50% of callers.",
    "Feature flag `verbose_answers` enabled for internal users.",
    "Web tier autoscaler policy updated.",
    "Gateway connection-pool size raised from 200 to 400.",
]


def _validate(spec):
    causes = spec["causes"]
    unknown = [c for c in causes if c not in ROOT_CAUSES or c in ("healthy", "other")]
    if unknown or len(causes) > 2 or len(set(causes)) != len(causes):
        raise ValueError(f"Invalid causes in {spec['name']}")
    config = [c for c in causes if c in CONFIG_FAULT_KNOBS]
    runtime = [c for c in causes if c in RUNTIME_FAULTS]
    if config and runtime:
        raise ValueError(f"{spec['name']}: config and runtime faults have different onsets; not allowed")
    if "underutilization" in causes and len(causes) > 1:
        raise ValueError(f"{spec['name']}: underutilization cannot be compounded")


def generate_hard(study):
    """Return (scenarios, answer_keys) for the Hard set, deterministically."""
    if not study.get("capacity_rps"):
        raise ValueError("Calibrate capacity_rps on the GPU before generating scenarios")
    rng = random.Random(study["seed"])
    capacity = float(study["capacity_rps"])
    base_rate = capacity * study["base_load_fraction"]
    pre, fault = study["timing"]["pre_onset_s"], study["timing"]["fault_s"]
    duration = pre + fault
    base_mix = study["base_mix"]
    specs = study["hard_incidents"]
    for spec in specs:
        _validate(spec)
    order = list(range(len(specs)))
    rng.shuffle(order)
    scenarios, answers = [], []
    for number, index in enumerate(order):
        spec = specs[index]
        causes = list(spec["causes"])
        incident_id = f"hard-{number + 1:02d}"
        engine = copy.deepcopy(study["engine_base"])
        diff = {}
        fault_knobs = []
        for cause in causes:
            if cause in CONFIG_FAULT_KNOBS:
                knob = CONFIG_FAULT_KNOBS[cause]
                fault_knobs.append(knob)
                diff[knob] = [engine[knob], spec["engine"][knob]]
                engine[knob] = spec["engine"][knob]
        forced = list(spec.get("benign_knobs_forced", []))
        excluded = set(fault_knobs).union(*(INTERACTING_KNOBS.get(c, set()) for c in causes))
        if excluded & set(forced):
            raise ValueError(f"{spec['name']}: a forced benign knob interacts with its fault")
        pool = [k for k in BENIGN_KNOBS if k not in excluded and k not in forced]
        benign = forced + rng.sample(pool, spec.get("benign_knobs", 0))
        for knob in benign:
            diff[knob] = [engine[knob], BENIGN_KNOBS[knob]]
            engine[knob] = BENIGN_KNOBS[knob]
        diff.update(rng.choice(BENIGN_CONFIG_DIFFS))

        if any(c in CONFIG_FAULT_KNOBS for c in causes) or "underutilization" in causes:
            onset = 0
        elif causes:
            onset = pre
        else:
            onset = None

        schedule = [_phase(0, base_rate, base_mix)]
        rate, mix = base_rate, dict(base_mix)
        if "traffic_surge" in causes:
            rate = capacity * spec["surge_multiplier"]
        if "long_prompt_flood" in causes:
            long = spec["long_fraction"]
            mix = {"short": base_mix["short"] * (1 - long), "medium": base_mix["medium"] * (1 - long), "long": long}
        if rate != base_rate or mix != base_mix:
            schedule.append(_phase(pre, rate, mix))
        if "underutilization" in causes:
            schedule = [_phase(0, capacity * spec["load_fraction"], base_mix)]
        if not causes and spec.get("spike"):
            start = round(rng.uniform(30, duration - 60), 1)
            schedule = [_phase(0, base_rate, base_mix),
                        _phase(start, base_rate * spec["spike"]["multiplier"], base_mix),
                        _phase(round(start + spec["spike"]["seconds"], 1), base_rate, base_mix)]

        names = rng.sample(JOB_MODULES, len(JOB_MODULES))
        jobs = []
        if "gpu_contention" in causes:
            jobs.append({"role": "contention", "module": names.pop(), "onset_s": pre,
                         "duty": spec["contention_duty"], "matrix_size": study["contention"]["matrix_size"],
                         "period": study["contention"]["period"]})
        if spec.get("decoy"):
            decoy = study["decoy"]
            jobs.append({"role": "decoy", "module": names.pop(), "onset_s": round(rng.uniform(5, 60), 1),
                         "duty": decoy["duty"], "matrix_size": decoy["matrix_size"], "period": decoy["period"]})

        events = [{"t": 0.0, "kind": "deploy", "text": "Serving deployment rolled out.",
                   "config_diff": dict(sorted(diff.items()))},
                  {"t": round(rng.uniform(10, duration - 30), 1), "kind": "note", "text": rng.choice(BENIGN_EVENTS)}]
        for _ in range(spec.get("noise_alerts", 0)):
            events.append({"t": round(rng.uniform(10, duration - 30), 1), "kind": "alert",
                           "text": rng.choice(NOISE_ALERTS)})
        if spec.get("herring_change"):
            anchor = onset if onset else pre
            events.append({"t": round(max(5.0, anchor - rng.uniform(5, 20)), 1), "kind": "change",
                           "text": rng.choice(HERRING_CHANGES)})
        events.sort(key=lambda row: row["t"])

        scenarios.append({"id": incident_id, "split": "hard", "engine": engine, "dtype": study["dtype"],
                          "schedule": schedule, "duration_s": duration, "contention": None, "jobs": jobs,
                          "events": events, "max_output_tokens": study["max_output_tokens"],
                          "request_timeout_s": study["request_timeout_s"], "slo": study["slo"],
                          "workload_seed": rng.randrange(2**31)})
        truth = causes or ["healthy"]
        answers.append({"id": incident_id, "split": "hard", "root_cause": truth[0], "root_causes": truth,
                        "severity_index": 0, "variant": spec["name"],
                        "params": {k: v for k, v in spec.items() if k not in ("name", "causes")},
                        "onset_s": onset, "fault_window_s": [onset, duration] if onset is not None else None,
                        "description": " + ".join(ROOT_CAUSES[c] for c in truth),
                        "red_herrings": {"benign_knobs": benign, "decoy": bool(spec.get("decoy")),
                                         "noise_alerts": spec.get("noise_alerts", 0),
                                         "herring_change": bool(spec.get("herring_change"))}})
    scenarios.append({"id": "reference", "split": "reference", "engine": copy.deepcopy(study["engine_base"]),
                      "dtype": study["dtype"], "schedule": [_phase(0, base_rate, base_mix)],
                      "duration_s": 180, "contention": None, "jobs": [],
                      "events": [{"t": 0.0, "kind": "deploy", "text": "Serving deployment rolled out.",
                                  "config_diff": {}}],
                      "max_output_tokens": study["max_output_tokens"],
                      "request_timeout_s": study["request_timeout_s"], "slo": study["slo"],
                      "workload_seed": rng.randrange(2**31)})
    return scenarios, answers


def write_hard_study(study, out_dir):
    """Write scenarios.json (runner input) and answers/answer_keys.json (sealed) for the Hard set."""
    out = Path(out_dir)
    scenarios, answers = generate_hard(study)
    (out / "answers").mkdir(parents=True, exist_ok=False)
    payload = {"schema_version": 1, "set": "hard", "study_sha256": digest(study), "scenarios": scenarios}
    (out / "scenarios.json").write_text(json.dumps(payload, indent=2) + "\n")
    keys = {"schema_version": 1, "set": "hard", "study_sha256": digest(study), "answers": answers}
    (out / "answers" / "answer_keys.json").write_text(json.dumps(keys, indent=2) + "\n")
    commitment = {"answer_keys_sha256": digest(keys), "scenarios_sha256": digest(payload)}
    (out / "commitment.json").write_text(json.dumps(commitment, indent=2) + "\n")
    return commitment
