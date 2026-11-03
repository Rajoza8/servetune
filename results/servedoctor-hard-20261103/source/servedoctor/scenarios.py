"""Seeded ServeIncidents scenarios: runner inputs plus separately sealed answer keys.

A scenario is everything the recorder needs (engine config, workload schedule,
fault parameters, change log). It is private to the runner. Agents only ever
see what the recorder observed. Incident IDs are shuffled so an ID reveals
nothing about the fault.
"""
from __future__ import annotations

import copy
import json
import math
import random
from pathlib import Path

from servetune.artifacts import digest

from .catalog import ROOT_CAUSES

BENIGN_EVENTS = [
    "Rotated the gateway TLS certificate.",
    "Updated the Grafana serving dashboard layout.",
    "Raised application log retention from 7 to 14 days.",
    "Client SDK minor version bump rolled out to 10% of callers.",
    "On-call handoff: no open incidents.",
    "Scheduled vulnerability scan completed on the host.",
    "Alert routing rules re-synced from source control.",
]

BENIGN_CONFIG_DIFFS = [
    {"request_timeout_s": [120, 180]},
    {"log_level": ["INFO", "WARNING"]},
    {"metrics_scrape_interval_s": [15, 10]},
]

TOKENS_PER_CHAR = 0.25


def estimate_tokens(text):
    return max(1, math.ceil(len(text) * TOKENS_PER_CHAR))


def load_questions(data_dir):
    """GSM8K training questions (MIT) from a ServeTune `prepare-data` directory."""
    path = Path(data_dir) / "source" / "train.jsonl"
    questions = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                question = json.loads(line)["question"].strip()
                if question:
                    questions.append(question)
    if len(questions) < 100:
        raise ValueError("Expected the GSM8K training split")
    return questions


def build_prompt_pools(questions, token_ranges, seed, per_class=48):
    """Short prompts are single questions; medium/long concatenate several and ask for the last."""
    rng = random.Random(seed)
    pools = {"short": [q for q in rng.sample(questions, min(per_class, len(questions)))]}
    for name in ("medium", "long"):
        low, high = token_ranges[name]
        pool = []
        for _ in range(per_class):
            target = rng.randint(low, high)
            parts = []
            while estimate_tokens("\n\n".join(parts)) < target:
                parts.append(rng.choice(questions))
            body = "\n\n".join(f"Problem {i + 1}: {p}" for i, p in enumerate(parts))
            pool.append(body + "\n\nSolve only the final problem and give its numeric answer.")
        pools[name] = pool
    return pools


def schedule_rate(schedule, t):
    phase = schedule[0]
    for row in schedule:
        if row["start_s"] <= t:
            phase = row
    return phase


def make_arrivals(scenario, pools):
    """Deterministic open-loop arrivals from the scenario's piecewise schedule."""
    rng = random.Random(scenario["workload_seed"])
    rows, t, duration = [], 0.0, scenario["duration_s"]
    while True:
        phase = schedule_rate(scenario["schedule"], t)
        t += rng.expovariate(phase["rate_rps"])
        if t >= duration:
            break
        phase = schedule_rate(scenario["schedule"], t)
        mix = phase["mix"]
        draw, cls = rng.random(), "short"
        acc = 0.0
        for name in ("short", "medium", "long"):
            acc += mix.get(name, 0.0)
            if draw < acc:
                cls = name
                break
        prompt = rng.choice(pools[cls])
        rows.append({"id": f"r{len(rows):05d}", "t": round(t, 4), "cls": cls, "prompt": prompt,
                     "prompt_tokens_est": estimate_tokens(prompt),
                     "max_tokens": scenario["max_output_tokens"]})
    return rows


def _phase(start, rate, mix):
    return {"start_s": start, "rate_rps": round(rate, 4), "mix": dict(mix)}


def generate(study):
    """Return (scenarios, answer_keys) for the whole study, deterministically."""
    if not study.get("capacity_rps"):
        raise ValueError("Calibrate capacity_rps on the GPU before generating scenarios")
    rng = random.Random(study["seed"])
    capacity = float(study["capacity_rps"])
    base_rate = capacity * study["base_load_fraction"]
    timing = study["timing"]
    pre, fault = timing["pre_onset_s"], timing["fault_s"]
    duration = pre + fault
    base_mix = study["base_mix"]
    faults = study["faults"]
    dev_index = study["split"]["dev_severity_index"]
    specs = []  # (root_cause, severity_index, params)
    for cause in ("traffic_surge", "long_prompt_flood", "kv_cache_starvation", "batch_limit_too_low",
                  "context_limit_too_small", "gpu_contention"):
        key = next(k for k in faults[cause] if k != "matrix_size")
        for index, value in enumerate(faults[cause][key]):
            specs.append((cause, index, {key: value}, "dev" if index == dev_index else "test"))
    for index, value in enumerate(faults["underutilization"]["load_fraction"]):
        split = "dev" if index < study["split"]["dev_underutilization"] else "test"
        specs.append(("underutilization", index, {"load_fraction": value}, split))
    for index in range(faults["healthy"]["variants"]):
        split = "dev" if index < study["split"]["dev_healthy"] else "test"
        specs.append(("healthy", index, {}, split))

    order = list(range(len(specs)))
    rng.shuffle(order)
    scenarios, answers = [], []
    for number, spec_index in enumerate(order):
        cause, severity, params, split = specs[spec_index]
        incident_id = f"inc-{number + 1:02d}"
        engine = copy.deepcopy(study["engine_base"])
        schedule = [_phase(0, base_rate, base_mix)]
        events = []
        onset = pre
        contention = None
        benign_t = rng.uniform(10, duration - 30)
        events.append({"t": round(benign_t, 1), "kind": "note", "text": rng.choice(BENIGN_EVENTS)})
        config_diff = None
        if cause == "traffic_surge":
            schedule.append(_phase(pre, capacity * params["capacity_multiplier"], base_mix))
        elif cause == "long_prompt_flood":
            long = params["long_fraction"]
            schedule.append(_phase(pre, base_rate, {"short": base_mix["short"] * (1 - long),
                                                    "medium": base_mix["medium"] * (1 - long),
                                                    "long": long}))
        elif cause in ("kv_cache_starvation", "batch_limit_too_low", "context_limit_too_small"):
            knob = next(iter(params))
            onset = 0
            config_diff = {knob: [engine[knob], params[knob]]}
            engine[knob] = params[knob]
        elif cause == "gpu_contention":
            contention = {"onset_s": pre, "duty": params["duty"],
                          "matrix_size": faults["gpu_contention"]["matrix_size"]}
        elif cause == "underutilization":
            schedule = [_phase(0, capacity * params["load_fraction"], base_mix)]
            onset = 0
        elif cause == "healthy":
            onset = None
            spike_at = rng.uniform(30, duration - 60)
            spike_rate = base_rate * faults["healthy"]["spike_multiplier"]
            schedule = [_phase(0, base_rate, base_mix), _phase(round(spike_at, 1), spike_rate, base_mix),
                        _phase(round(spike_at + faults["healthy"]["spike_s"], 1), base_rate, base_mix)]
        # Every incident starts with a deploy event so a t=0 change is never a giveaway.
        diff = dict(rng.choice(BENIGN_CONFIG_DIFFS))
        if config_diff:
            diff.update(config_diff)
        events.append({"t": 0.0, "kind": "deploy", "text": "Serving deployment rolled out.",
                       "config_diff": dict(sorted(diff.items()))})
        events.sort(key=lambda row: row["t"])
        scenario = {"id": incident_id, "split": split, "engine": engine, "dtype": study["dtype"],
                    "schedule": schedule, "duration_s": duration, "contention": contention,
                    "events": events, "max_output_tokens": study["max_output_tokens"],
                    "request_timeout_s": study["request_timeout_s"], "slo": study["slo"],
                    "workload_seed": rng.randrange(2**31)}
        scenarios.append(scenario)
        answers.append({"id": incident_id, "split": split, "root_cause": cause,
                        "severity_index": severity, "params": params, "onset_s": onset,
                        "fault_window_s": [onset, duration] if onset is not None else None,
                        "description": ROOT_CAUSES[cause]})
    # A healthy reference recording gives every arm the same "normal profile".
    scenarios.append({"id": "reference", "split": "reference", "engine": copy.deepcopy(study["engine_base"]),
                      "dtype": study["dtype"], "schedule": [_phase(0, base_rate, base_mix)],
                      "duration_s": 180, "contention": None,
                      "events": [{"t": 0.0, "kind": "deploy", "text": "Serving deployment rolled out.",
                                  "config_diff": {}}],
                      "max_output_tokens": study["max_output_tokens"],
                      "request_timeout_s": study["request_timeout_s"], "slo": study["slo"],
                      "workload_seed": rng.randrange(2**31)})
    return scenarios, answers


def write_study(study, out_dir):
    """Write scenarios.json (runner input) and answers/answer_keys.json (sealed)."""
    out = Path(out_dir)
    scenarios, answers = generate(study)
    (out / "answers").mkdir(parents=True, exist_ok=False)
    payload = {"schema_version": 1, "study_sha256": digest(study), "scenarios": scenarios}
    (out / "scenarios.json").write_text(json.dumps(payload, indent=2) + "\n")
    keys = {"schema_version": 1, "study_sha256": digest(study), "answers": answers}
    (out / "answers" / "answer_keys.json").write_text(json.dumps(keys, indent=2) + "\n")
    commitment = {"answer_keys_sha256": digest(keys), "scenarios_sha256": digest(payload)}
    (out / "commitment.json").write_text(json.dumps(commitment, indent=2) + "\n")
    return commitment
