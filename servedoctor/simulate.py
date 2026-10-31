"""Synthetic incidents from a toy queueing model, for rehearsal and tests only.

Every file it writes is marked mode=synthetic. Synthetic incidents must never
be reported as ServeIncidents results; they exist to exercise the pipeline.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import random

from servetune.artifacts import seal, write_json

from .record import engine_knobs
from .scenarios import generate, schedule_rate


def _poisson(rng, mean):
    limit, k, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        k += 1
        product *= rng.random()
    return k


def _capacity(scenario, answer, t, base_capacity):
    cfg = scenario["engine"]
    capacity = base_capacity
    capacity *= min(1.0, cfg["max_num_seqs"] / 24)
    if cfg["gpu_memory_utilization"] < 0.85:
        capacity *= max(0.15, (cfg["gpu_memory_utilization"] - 0.7) / 0.2)
    contention = scenario.get("contention")
    if contention and t >= contention["onset_s"]:
        capacity *= 1 - 0.55 * contention["duty"]
    mix = schedule_rate(scenario["schedule"], t)["mix"]
    capacity *= 1 - 0.65 * mix.get("long", 0.0)
    return capacity


def simulate_study(study, out_dir, seed=7):
    out = Path(out_dir)
    scenarios, answers = generate(study)
    by_id = {a["id"]: a for a in answers}
    (out / "answers" / "runtime").mkdir(parents=True, exist_ok=False)
    write_json(out / "answers" / "answer_keys.json", {"schema_version": 1, "mode": "synthetic", "answers": answers})
    rng = random.Random(seed)
    base_capacity = float(study["capacity_rps"])
    for scenario in scenarios:
        answer = by_id.get(scenario["id"], {"root_cause": "healthy"})
        inc = out / "incidents" / scenario["id"]
        inc.mkdir(parents=True)
        knobs = engine_knobs(scenario["engine"])
        write_json(inc / "engine_config.json", knobs)
        write_json(inc / "events.json", scenario["events"])
        write_json(inc / "slo.json", scenario["slo"])
        queue, gen_total, prompt_total, preempt_total = 0.0, 0.0, 0.0, 0.0
        rows = []
        for second in range(1, int(scenario["duration_s"]) + 1):
            t = float(second)
            phase = schedule_rate(scenario["schedule"], t)
            mix = phase["mix"]
            arrivals = _poisson(rng, phase["rate_rps"])
            capacity = _capacity(scenario, answer, t, base_capacity)
            medium = sum(1 for _ in range(arrivals) if rng.random() < mix.get("medium", 0))
            errors = {}
            if knobs["max_model_len"] < 1500 and medium:
                errors["http_400"] = medium
            admitted = arrivals - errors.get("http_400", 0)
            queue = max(0.0, queue + admitted - capacity)
            served = min(capacity, admitted + queue)
            latency = 2.0 + queue / max(capacity, 0.1)
            gen_total += served * 110
            prompt_mean = 120 * mix.get("short", 0) + 1000 * mix.get("medium", 0) + 2900 * mix.get("long", 0)
            prompt_total += served * prompt_mean
            running = min(knobs["max_num_seqs"], served * latency)
            if knobs["gpu_memory_utilization"] < 0.85:
                preempt_total += served * 0.3
            kv = min(100.0, running / knobs["max_num_seqs"] * 60 + (35 if knobs["gpu_memory_utilization"] < 0.85 else 0))
            processes = [{"pid": 1234, "used_mb": 80000, "command": "vllm serve meta-models/Muse-Glimmer-30B"}]
            contention = scenario.get("contention")
            if contention and t >= contention["onset_s"]:
                processes.append({"pid": 4242, "used_mb": 900,
                                  "command": "python3 -m servedoctor.jobs.embedding_batch --seconds 300"})
            load = served / base_capacity
            rows.append({"t": t, "mode": "synthetic",
                         "vllm": {"running": round(running, 1), "waiting": round(queue, 1), "kv_usage": round(kv, 1),
                                  "preemptions_total": preempt_total, "generation_tokens_total": gen_total,
                                  "prompt_tokens_total": prompt_total},
                         "gpu": {"power_w": 470 if load > 0.02 else 90, "util_gpu": min(100, 60 + 40 * load),
                                 "mem_used_mb": 88000, "processes": processes},
                         "client": {"arrivals": arrivals, "admitted": arrivals, "shed": 0,
                                    "arrival_prompt_tokens_est_mean": prompt_mean if arrivals else None,
                                    "completed_ok": int(served), "errors": errors,
                                    "latencies_s": [round(latency * rng.uniform(0.8, 1.2), 2)
                                                    for _ in range(int(served))],
                                    "ttfts_s": [round(latency * 0.2, 2)] * int(served),
                                    "completion_tokens": int(served * 110)},
                         "gateway": {"max_rps": None, "max_prompt_tokens": None},
                         "engine_config": knobs, "log": []})
        with (inc / "telemetry.jsonl").open("x") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        (inc / "requests.jsonl").write_text("")
        write_json(inc / "recording.json", {"duration_s": scenario["duration_s"], "mode": "synthetic",
                                            "telemetry_rows": len(rows)})
        seal(inc)
        pids = [4242] if scenario.get("contention") else []
        if scenario["id"] != "reference":
            write_json(out / "answers" / "runtime" / f"{scenario['id']}.json",
                       {"id": scenario["id"], "contention_pids": pids})
    return out
