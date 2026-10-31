"""Closed-loop live runs: inject a fault, let an arm act once, verify recovery or roll back.

Only whitelisted actions execute. Engine changes restart vLLM with one changed
knob. A GPU process can be stopped only if this run launched it (environment
marker check). Recovery is measured on the requests themselves.
"""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from servetune.artifacts import timestamp, write_json

from .catalog import validate_action, ActionError
from .evaluate import _model_decision, _monitor, _rules_decision
from .loadgen import Gateway, LoadGenerator, http_request, summarize
from .observe import observe
from .record import ContentionJob, engine_knobs, serving_config
from .scenarios import make_arrivals
from .telemetry import LogTail, Recorder, read_jsonl


class EngineSlot:
    def __init__(self, engine_factory, serving, knobs, run_dir):
        self.factory, self.serving, self.run_dir = engine_factory, serving, Path(run_dir)
        self.knobs = dict(knobs)
        self.generation = 0
        self.engine = None
        self.lock = threading.Lock()
        self.restarts = []

    def start(self):
        path = self.run_dir / "engines" / f"engine-{self.generation}"
        self.engine = self.factory(serving_config(self.serving, self.knobs), path, self.serving.get("dtype", "bf16"))
        self.engine.start()
        return self.engine

    @property
    def base_url(self):
        return self.engine.base_url if self.engine else None

    def restart(self, knob, value):
        with self.lock:
            started = time.monotonic()
            old = self.engine
            self.engine = None
            old.stop()
            write_json(self.run_dir / "engines" / f"engine-{self.generation}" / "engine_metadata.json", old.metadata)
            self.knobs[knob] = value
            self.generation += 1
            self.start()
            self.restarts.append({"knob": knob, "value": value, "seconds": time.monotonic() - started})

    def stop(self):
        if self.engine is not None:
            self.engine.stop()
            write_json(self.run_dir / "engines" / f"engine-{self.generation}" / "engine_metadata.json",
                       self.engine.metadata)


class _SlotTail:
    """Follow the current engine's log across restarts."""
    def __init__(self, slot):
        self.slot, self.generation, self.tail = slot, None, None

    def read(self):
        engine = self.slot.engine
        if engine is None:
            return []
        if self.generation != self.slot.generation:
            self.tail = LogTail(Path(engine.artifact_dir) / "engine.log")
            self.generation = self.slot.generation
        return self.tail.read()


def _window_ok(outcomes, start, end, slo):
    s = summarize(outcomes, start, end)
    ok = (s["ok"] > 0 and s["p95_latency_s"] is not None and s["p95_latency_s"] <= slo["p95_latency_s"]
          and s["error_rate"] <= slo["max_error_rate"])
    return ok, s


def run_live(scenario, answer_onset, *, arm, clients, serving, pools, run_dir, engine_factory,
             gpu_factory=None, job_factory=ContentionJob, profile=None, reference_config=None,
             checkpoint_s=30, recovery_window_s=60, verify_s=150, lag_s=60, extra_s=300, log=print):
    run = Path(run_dir)
    run.mkdir(parents=True, exist_ok=False)
    duration = scenario["duration_s"] + extra_s
    slo = scenario["slo"]
    slot = EngineSlot(engine_factory, serving, engine_knobs(scenario["engine"]), run)
    slot.start()
    gateway = Gateway()
    timeout = scenario["request_timeout_s"]

    def request(row):
        base = slot.base_url
        if base is None:
            return {"status": "connection_error"}
        return http_request(base, row, timeout)

    live_scenario = dict(scenario, duration_s=duration)
    loadgen = LoadGenerator(make_arrivals(live_scenario, pools), gateway, request)
    gpu = gpu_factory() if gpu_factory else None
    t0 = time.monotonic()
    telemetry_path = run / "telemetry.jsonl"

    def metrics_url():
        return slot.base_url[: -len("/v1")] + "/metrics" if slot.base_url else "http://127.0.0.1:9/metrics"

    class _Scrape:
        def __call__(self, _url):
            from .telemetry import scrape_metrics
            return scrape_metrics(metrics_url())

    tail = _SlotTail(slot)
    recorder = Recorder(telemetry_path, clock_zero=t0, metrics_url="dynamic", gpu=gpu, loadgen=loadgen,
                        gateway=gateway, log_tail=tail, config_fn=lambda: dict(slot.knobs), scrape=_Scrape())
    events = list(scenario["events"])
    write_json(run / "scenario_public.json", {"id": scenario["id"], "slo": slo, "duration_s": duration,
                                               "arm": arm, "started_at": timestamp()})
    job = None
    contention = scenario.get("contention")
    result = {"id": scenario["id"], "arm": arm, "decision": None, "actions": [], "executed": [],
              "recovered": None, "rolled_back": False}
    recorder.start()
    loadgen.start(start_time=t0)
    timer = None
    try:
        if contention:
            job = job_factory()
            timer = threading.Timer(contention["onset_s"], lambda: job.start(
                duration - contention["onset_s"] + 60, contention["duty"], contention["matrix_size"]))
            timer.start()
        acted_at = None
        next_check = checkpoint_s
        while time.monotonic() - t0 < duration:
            time.sleep(max(0.0, min(1.0, t0 + next_check - time.monotonic())))
            now = time.monotonic() - t0
            if now < next_check:
                continue
            next_check += checkpoint_s
            if acted_at is not None:
                if now - acted_at >= verify_s and result["recovered"] is None:
                    # Judge requests old enough to have finished or timed out.
                    ok, summary = _window_ok(loadgen.outcomes, now - recovery_window_s - lag_s, now - lag_s, slo)
                    result["post_fix_window"] = summary
                    result["recovered"] = ok
                    if not ok:
                        _rollback(result, slot, gateway, log)
                continue
            incident = {"id": scenario["id"], "telemetry": read_jsonl(telemetry_path), "events": events,
                        "engine_config": dict(slot.knobs), "slo": slo, "recording": {"duration_s": duration}}
            observation = observe(incident, now, profile=profile, reference_config=reference_config)
            decision = _decide(arm, clients, observation)
            if not decision.get("incident"):
                continue
            result["decision"] = {**decision, "t": round(now, 1)}
            log(f"{scenario['id']} {arm}: {decision['root_cause']} at {now:.0f}s -> {decision['actions']}")
            acted_at = time.monotonic() - t0
            for action in decision["actions"]:
                result["executed"].append(_execute(action, slot, gateway, job, log))
            acted_at = time.monotonic() - t0
            result["acted_at_s"] = round(acted_at, 1)
            events.append({"t": round(acted_at, 1), "kind": "agent_action",
                           "text": json.dumps(decision["actions"])})
        loadgen.wait(drain_timeout_s=timeout + 10)
    finally:
        loadgen.stop()
        if timer:
            timer.cancel()
        if job:
            job.stop()
        recorder.stop()
        slot.stop()
        if gpu:
            gpu.stop()
    onset = answer_onset if answer_onset is not None else 0
    result["fault_window_before_action"] = summarize(loadgen.outcomes, onset,
                                                     result.get("acted_at_s") or duration)
    result["after_action"] = (summarize(loadgen.outcomes, result["acted_at_s"], duration)
                              if result.get("acted_at_s") else None)
    result["time_to_recover_s"] = _time_to_recover(loadgen.outcomes, result, onset, duration, slo)
    result["engine_restarts"] = slot.restarts
    with (run / "requests.jsonl").open("x") as stream:
        for row in sorted(loadgen.outcomes, key=lambda r: r["t_sched"]):
            stream.write(json.dumps(row) + "\n")
    write_json(run / "live_result.json", result)
    return result


def _decide(arm, clients, observation):
    try:
        if arm == "rules":
            return _rules_decision(observation)
        if arm == "glimmer_to_spark":
            monitor = _monitor(clients["glimmer"], observation)
            if monitor["status"] == "healthy":
                return {"incident": False}
            return _model_decision(clients["spark"], observation)
        return _model_decision(clients[arm], observation)
    except Exception as exc:
        return {"incident": False, "error": type(exc).__name__}


def _execute(action, slot, gateway, job, log):
    record = {"action": action, "at": timestamp()}
    try:
        action = validate_action(action, current_config=slot.knobs)
        kind = action["type"]
        if kind == "gateway_rate_limit":
            record["previous"] = gateway.policy()
            gateway.set_policy(max_rps=action["max_rps"])
        elif kind == "gateway_max_prompt_tokens":
            record["previous"] = gateway.policy()
            gateway.set_policy(max_prompt_tokens=action["max_prompt_tokens"])
        elif kind == "set_engine_config":
            record["previous"] = {action["knob"]: slot.knobs.get(action["knob"])}
            slot.restart(action["knob"], action["value"])
        elif kind == "stop_gpu_process":
            if job is None or not job.owns(action["pid"]):
                record["status"] = "refused: process not launched by this run"
                return record
            job.stop()
        record["status"] = "executed"
    except ActionError as exc:
        record["status"] = f"rejected: {exc}"
    except Exception as exc:
        record["status"] = f"failed: {type(exc).__name__}"
    log(f"  action {record['action']} -> {record['status']}")
    return record


def _rollback(result, slot, gateway, log):
    for item in reversed(result["executed"]):
        if item.get("status") != "executed" or "previous" not in item:
            continue
        action = item["action"]
        if action["type"].startswith("gateway_"):
            previous = item["previous"]
            gateway.set_policy(max_rps=previous["max_rps"], max_prompt_tokens=previous["max_prompt_tokens"])
        elif action["type"] == "set_engine_config":
            knob, value = next(iter(item["previous"].items()))
            slot.restart(knob, value)
    result["rolled_back"] = True
    log("  not recovered: rolled back and escalated to a human")


def _time_to_recover(outcomes, result, onset, duration, slo, window=30):
    if not result.get("acted_at_s") or not result.get("recovered"):
        return None
    t = result["acted_at_s"]
    while t + window <= duration:
        ok, _ = _window_ok(outcomes, t, t + window, slo)
        if ok:
            return round(t + window - onset, 1)
        t += 10
    return None
