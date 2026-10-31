"""Record ServeIncidents on the GPU: real vLLM, real faults, once-per-second telemetry.

Agents never read scenarios.json or answers/. Each incident directory holds only
what an operator could observe, and is sealed with a SHA-256 manifest.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time

from servetune.artifacts import seal, timestamp, write_json

from .loadgen import Gateway, LoadGenerator, http_request, summarize
from .scenarios import make_arrivals
from .telemetry import LogTail, Recorder, environment_marker_matches, scrape_metrics

ENGINE_KNOB_KEYS = ("max_model_len", "max_num_seqs", "max_num_batched_tokens",
                    "gpu_memory_utilization", "enable_chunked_prefill", "enable_prefix_caching")


class ContentionJob:
    """Launch and stop only the batch job this instance created (marker-verified)."""
    def __init__(self, gpu_index=0):
        self.gpu_index = gpu_index
        self.marker = "SERVEDOCTOR_JOB_OWNER=" + secrets.token_hex(12)
        self.process = None

    def start(self, seconds, duty, size):
        env = dict(os.environ)
        for name in list(env):
            if name.endswith("_API_KEY"):
                env.pop(name)
        key, value = self.marker.split("=", 1)
        env[key] = value
        env.setdefault("CUDA_VISIBLE_DEVICES", str(self.gpu_index))
        self.process = subprocess.Popen(
            [sys.executable, "-m", "servedoctor.jobs.embedding_batch", "--seconds", str(seconds),
             "--duty", str(duty), "--size", str(size)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return self.process.pid

    def owns(self, pid):
        return self.process is not None and pid == self.process.pid and environment_marker_matches(pid, self.marker)

    def stop(self):
        if self.process is None or self.process.poll() is not None:
            return
        if environment_marker_matches(self.process.pid, self.marker):
            os.killpg(self.process.pid, signal.SIGTERM)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=5)


def engine_knobs(scenario_engine):
    return {k: scenario_engine[k] for k in ENGINE_KNOB_KEYS if k in scenario_engine}


def serving_config(serving, knobs):
    """Merge fixed serving identity (model, revision, port) with incident knobs."""
    config = {k: v for k, v in serving.items() if k != "dtype"}
    config.update(knobs)
    config["use_engine_defaults"] = False
    return config


def wait_idle(metrics_url, timeout_s=90, scrape=scrape_metrics):
    deadline = time.monotonic() + timeout_s
    quiet_since = None
    while time.monotonic() < deadline:
        try:
            row = scrape(metrics_url)
            busy = row.get("running", 0) + row.get("waiting", 0)
        except Exception:
            busy = 1
        now = time.monotonic()
        if busy == 0:
            quiet_since = quiet_since or now
            if now - quiet_since >= 5:
                return True
        else:
            quiet_since = None
        time.sleep(1)
    return False


def record_incident(scenario, *, engine, pools, out_dir, gpu=None, job_factory=ContentionJob,
                    request_timeout_s=None, drain_timeout_s=90, sleeper=time.sleep):
    """Run one scenario against an already-running engine and write its incident directory."""
    inc = Path(out_dir) / "incidents" / scenario["id"]
    inc.mkdir(parents=True, exist_ok=False)
    knobs = engine_knobs(scenario["engine"])
    write_json(inc / "engine_config.json", knobs)
    write_json(inc / "events.json", scenario["events"])
    write_json(inc / "slo.json", scenario["slo"])
    write_json(inc / "engine_identity.json", {k: engine.metadata.get(k) for k in (
        "model_id", "model_revision", "vllm_version", "dtype", "gpu_uuid", "kernel_backend_lines")})
    arrivals = make_arrivals(scenario, pools)
    gateway = Gateway()
    timeout = request_timeout_s or scenario["request_timeout_s"]
    base_url = engine.base_url
    metrics_url = base_url[: -len("/v1")] + "/metrics"
    loadgen = LoadGenerator(arrivals, gateway, lambda row: http_request(base_url, row, timeout))
    log_path = Path(engine.artifact_dir) / "engine.log"
    tail = LogTail(log_path)
    if log_path.exists():
        tail.offset = log_path.stat().st_size
    t0 = time.monotonic()
    recorder = Recorder(inc / "telemetry.jsonl", clock_zero=t0, metrics_url=metrics_url, gpu=gpu,
                        loadgen=loadgen, gateway=gateway, log_tail=tail, config_fn=lambda: knobs)
    job, job_pid, timer = None, None, None
    contention = scenario.get("contention")
    started_at = timestamp()
    recorder.start()
    loadgen.start(start_time=t0)
    try:
        if contention:
            job = job_factory()

            def launch():
                nonlocal job_pid
                job_pid = job.start(scenario["duration_s"] - contention["onset_s"] + drain_timeout_s,
                                    contention["duty"], contention["matrix_size"])

            timer = threading.Timer(contention["onset_s"], launch)
            timer.start()
        sleeper(max(0.0, scenario["duration_s"] - (time.monotonic() - t0)))
        loadgen.wait(drain_timeout_s)
    finally:
        loadgen.stop()
        if timer is not None:
            timer.cancel()
        if job is not None:
            job.stop()
        recorder.stop()
    with (inc / "requests.jsonl").open("x", encoding="utf-8") as stream:
        for row in sorted(loadgen.outcomes, key=lambda r: r["t_sched"]):
            stream.write(json.dumps(row) + "\n")
    summary = summarize(loadgen.outcomes)
    write_json(inc / "recording.json", {"started_at": started_at, "duration_s": scenario["duration_s"],
                                        "telemetry_rows": recorder.rows, "telemetry_errors": recorder.errors,
                                        "requests": summary, "mode": "live"})
    seal(inc)
    runtime = {"id": scenario["id"], "contention_pids": [job_pid] if job_pid else []}
    answers_dir = Path(out_dir) / "answers" / "runtime"
    answers_dir.mkdir(parents=True, exist_ok=True)
    write_json(answers_dir / f"{scenario['id']}.json", runtime)
    return {"id": scenario["id"], "summary": summary, "telemetry_rows": recorder.rows}


def record_study(scenarios, *, serving, pools, out_dir, engine_factory, gpu_factory=None,
                 ids=None, log=print, **kwargs):
    """Record scenarios, grouping by engine knobs so each config starts only once."""
    chosen = [s for s in scenarios if ids is None or s["id"] in ids]
    groups = {}
    for scenario in chosen:
        key = json.dumps(engine_knobs(scenario["engine"]), sort_keys=True)
        groups.setdefault(key, []).append(scenario)
    results = []
    for number, (key, group) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))):
        knobs = json.loads(key)
        engine_dir = Path(out_dir) / "engines" / f"engine-{number:02d}-{group[0]['id']}"
        engine = engine_factory(serving_config(serving, knobs), engine_dir, serving.get("dtype", "bf16"))
        log(f"starting engine {engine_dir.name} for {[s['id'] for s in group]}")
        engine.start()
        try:
            metrics_url = engine.base_url[: -len("/v1")] + "/metrics"
            for scenario in group:
                wait_idle(metrics_url)
                gpu = gpu_factory() if gpu_factory else None
                try:
                    result = record_incident(scenario, engine=engine, pools=pools, out_dir=out_dir,
                                             gpu=gpu, **kwargs)
                finally:
                    if gpu is not None:
                        gpu.stop()
                log(f"recorded {scenario['id']}: {result['summary']}")
                results.append(result)
        finally:
            engine.stop()
            write_json(engine_dir / "engine_metadata.json", engine.metadata)
    return results


def calibrate(*, serving, study, pools, out_dir, engine_factory, rates, seconds=60, log=print):
    """Step the base workload's arrival rate to estimate capacity under the SLO."""
    from .scenarios import _phase
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    knobs = engine_knobs(study["engine_base"])
    engine = engine_factory(serving_config(serving, knobs), out / "engine", serving.get("dtype", "bf16"))
    engine.start()
    steps = []
    try:
        metrics_url = engine.base_url[: -len("/v1")] + "/metrics"
        for index, rate in enumerate(rates):
            wait_idle(metrics_url)
            scenario = {"schedule": [_phase(0, rate, study["base_mix"])], "duration_s": seconds,
                        "workload_seed": study["seed"] + index, "max_output_tokens": study["max_output_tokens"]}
            arrivals = make_arrivals(scenario, pools)
            gen = LoadGenerator(arrivals, Gateway(),
                                lambda row: http_request(engine.base_url, row, study["request_timeout_s"]))
            gen.start()
            gen.wait(drain_timeout_s=study["request_timeout_s"] + 30)
            waiting = scrape_metrics(metrics_url).get("waiting")
            summary = summarize(gen.outcomes)
            ok = (summary["p95_latency_s"] is not None and summary["p95_latency_s"] <= study["slo"]["p95_latency_s"]
                  and summary["error_rate"] <= study["slo"]["max_error_rate"])
            steps.append({"rate_rps": rate, **summary, "within_slo": ok, "waiting_after": waiting})
            log(f"rate {rate}: {summary} within_slo={ok}")
            if not ok:
                break
    finally:
        engine.stop()
    passing = [s["rate_rps"] for s in steps if s["within_slo"]]
    result = {"schema_version": 1, "created_at": timestamp(), "steps": steps,
              "capacity_rps": max(passing) if passing else None,
              "definition": "highest tested arrival rate whose p95 latency and error rate meet the SLO",
              "engine": engine.metadata.get("vllm_version")}
    write_json(out / "calibration.json", result)
    return result
