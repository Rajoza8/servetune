"""One live ServeDoctor diagnosis on a recorded incident, runnable by anyone.

With a Meta Model API key in the environment (`MODEL_API_KEY` or `META_API_KEY`),
it sends the agent's observation of a real recorded GPU incident to Muse Spark
(or Muse Wonder) and checks the reply against the sealed answer key. Without a
key it replays the reply the same model gave when the study was evaluated, and
says so. No GPU is needed. The model never sees the answer key: it is read
only after the reply, to grade it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from .catalog import ROOT_CAUSES, judge_actions, judge_compound
from .llm import Ledger, ModelClient, diagnose_system, normalize_decision, parse_json
from .observe import load_incident, normal_profile, observe, render

DEFAULT_STUDY = "results/servedoctor-hard-20261103/analysis"
DEFAULT_INCIDENT = "hard-13"
MODELS = {"spark": ("spark", None, 2048), "wonder": ("wonder", "muse-wonder-1.0", 4096)}
KEY_VARS = ("MODEL_API_KEY", "META_API_KEY")
LABELS = {"healthy": "Healthy", "traffic_surge": "Traffic surge", "long_prompt_flood": "Long-prompt flood",
          "kv_cache_starvation": "KV-cache starvation", "batch_limit_too_low": "Batch limit too low",
          "context_limit_too_small": "Context limit too small", "gpu_contention": "GPU contention",
          "underutilization": "Underused GPU", "other": "Other"}


class Style:
    def __init__(self, enabled):
        self.enabled = enabled

    def __call__(self, code, text):
        return f"\033[{code}m{text}\033[0m" if self.enabled else text


def _action(a):
    kind = a["type"]
    if kind == "set_engine_config":
        return f"restart the engine with {a['knob']} = {a['value']}"
    if kind == "gateway_rate_limit":
        return f"rate-limit the gateway to {a['max_rps']} requests/s"
    if kind == "gateway_max_prompt_tokens":
        return f"reject prompts over {a['max_prompt_tokens']} tokens"
    if kind == "stop_gpu_process":
        return f"stop GPU process {a['pid']}"
    return kind.replace("_", " ")


def _latest(observation):
    rows = observation["recent_10s_buckets"]
    return rows[-1] if rows else {}


def _summary_lines(observation):
    """The handful of signals a person would glance at; the model gets the full snapshot."""
    last = _latest(observation)
    profile = observation.get("normal_profile") or {}
    config, reference = observation["engine_config"], observation.get("reference_engine_config") or {}
    changed = [f"{k} {reference[k]}→{v}" for k, v in config.items() if k in reference and reference[k] != v]
    errors = sum((last.get("errors") or {}).values())
    lines = [
        f"traffic      {last.get('arrivals_rps')} req/s   (normal {profile.get('arrivals_rps')})",
        f"p95 latency  {last.get('p95_latency_s')} s       (SLO {observation['slo']['p95_latency_s']} s)",
        f"queue        {last.get('waiting_max')} waiting, {last.get('running')} running",
        f"KV cache     {last.get('kv_usage_pct_max')}% used",
        f"errors       {errors} in the last 10 s",
        "config diff  " + (", ".join(changed) if changed else "none"),
    ]
    for proc in observation.get("gpu_processes") or []:
        lines.append(f"GPU process  pid {proc['pid']}  {proc.get('used_mb')} MB  {proc.get('command')}")
    for event in observation.get("change_log") or []:
        lines.append(f"change log   {event['t']:>5.0f}s  {event['text']}")
    return lines


def _recorded_reply(study, incident_id, arm, at):
    path = study / "decisions" / arm / f"{incident_id}.json"
    trail = json.loads(path.read_text())["trail"]
    step = min(trail, key=lambda s: abs(s["t"] - at))
    decision = step.get("decision") or {}
    return decision.get("raw_output") or "", decision.get("usage") or {}, step["t"], path


def run_demo(*, study_dir=DEFAULT_STUDY, incident_id=DEFAULT_INCIDENT, at=None, model="spark", recorded=False,
             environ=None, transport=None, out=sys.stdout, color=None, evidence_dir="runs/demo",
             ledger_path="runs/servedoctor-demo-ledger.json"):
    environ = os.environ if environ is None else environ
    style = Style(out.isatty() if color is None else color)
    study = Path(study_dir)
    incident = load_incident(study / "incidents" / incident_id)
    reference_dir = study / "incidents" / "reference"
    reference = load_incident(reference_dir) if reference_dir.exists() else None
    profile = normal_profile(reference["telemetry"]) if reference else None
    if at is None:
        recorded_final = json.loads((study / "decisions" / "spark" / f"{incident_id}.json").read_text()).get("final")
        at = recorded_final["t"] if recorded_final else 150
    observation = observe(incident, at, profile=profile, reference_config=reference["engine_config"] if reference else None)
    prompt = render(observation)
    say = lambda text="": print(text, file=out, flush=True)

    say(style("1", f"ServeDoctor · incident {incident_id} · {int(at) // 60}:{int(at) % 60:02d} into a real GPU recording"))
    say(style("2", "What the agent sees (summary; the model gets the full 3-minute snapshot):"))
    for line in _summary_lines(observation):
        say("  " + line)
    say()

    client_name, model_id, max_tokens = MODELS[model]
    key = next((environ[k] for k in KEY_VARS if environ.get(k)), None)
    live = bool(key) and not recorded
    record = {"incident": incident_id, "at_s": at, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "mode": "live" if live else "recorded"}
    if live:
        ledger = Ledger(ledger_path)
        if not Path(ledger_path).exists():
            ledger.initialize()
        client = ModelClient(client_name, ledger=ledger, model=model_id, environ=environ, transport=transport)
        say(style("1;36", f"→ Calling {client.spec['model']} on the Meta Model API (live)…"))
        started = time.monotonic()
        text, usage = client.chat(diagnose_system(), prompt, max_tokens=max_tokens)
        elapsed = time.monotonic() - started
        cost = float(client.cost_usd)
        say(style("36", f"← Reply in {elapsed:.1f} s · {usage.get('prompt_tokens')} input + "
                        f"{usage.get('completion_tokens')} output tokens · ${cost:.4f}"))
        record.update(model=client.spec["model"], elapsed_s=round(elapsed, 2), usage=usage, cost_usd=cost,
                      called_at_utc=datetime.now(timezone.utc).isoformat())
    else:
        arm = model
        text, usage, step_t, path = _recorded_reply(study, incident_id, arm, at)
        reason = "--recorded was given" if recorded else "no MODEL_API_KEY is set"
        say(style("33", f"→ Recorded mode ({reason}): the reply this model gave at {step_t:.0f} s when the "
                        f"study was evaluated, from {path}"))
        record.update(model=arm, recorded_step_t=step_t, usage=usage, source=str(path))
    say()

    try:
        decision = normalize_decision(parse_json(text), current_config=observation["engine_config"])
    except (ValueError, json.JSONDecodeError):
        say(style("31", "The reply was not valid JSON (for example, the output budget ran out)."))
        say(text[:800])
        record["valid_output"] = False
        _save(evidence_dir, record, text) if live else None
        return record
    record.update(valid_output=True, decision={k: decision[k] for k in ("incident", "root_cause", "actions")})
    say(style("1", "Diagnosis: ") + LABELS.get(decision["root_cause"], decision["root_cause"]) + " — " +
        ROOT_CAUSES.get(decision["root_cause"], "").rstrip(".").lower() +
        (f"  (confidence {decision['confidence']})" if decision.get("confidence") is not None else ""))
    for item in decision.get("evidence") or []:
        say("  • " + item)
    if decision.get("explanation"):
        say("  " + decision["explanation"])
    for action in decision["actions"]:
        say(style("1", "Proposed fix: ") + _action(action))
    for rejected in decision.get("rejected_actions") or []:
        say(style("33", f"Rejected by the whitelist (never executed): {rejected['action']}"))
    say()

    # Grade only after the reply: the model never sees the answer key.
    answers = {a["id"]: a for a in json.loads((study / "answers" / "answer_keys.json").read_text())["answers"]}
    answer = answers[incident_id]
    runtime_path = study / "answers" / "runtime" / f"{incident_id}.json"
    runtime = json.loads(runtime_path.read_text()) if runtime_path.exists() else {}
    causes = answer.get("root_causes") or [answer["root_cause"]]
    kwargs = {"current_config": observation["engine_config"], "contention_pids": runtime.get("contention_pids", [])}
    judged = (judge_actions(causes[0], decision["actions"], **kwargs) if len(causes) == 1
              else judge_compound(causes, decision["actions"], **kwargs))
    right = decision["incident"] and decision["root_cause"] in causes
    decoys = set(runtime.get("decoy_pids", []))
    stopped_decoy = any(a["type"] == "stop_gpu_process" and a["pid"] in decoys for a in decision["actions"])
    mark = lambda ok: style("32", "✓") if ok else style("31", "✗")
    say(style("2", "Checked against the sealed answer key:"))
    say(f"  {mark(right)} root cause: {' + '.join(LABELS[c] for c in causes)}")
    say(f"  {mark(judged['fixes'] and not judged['harmful'])} proposed a valid, safe fix")
    if decoys:
        say(f"  {mark(not stopped_decoy)} left the harmless decoy job (pid {', '.join(map(str, sorted(decoys)))}) alone")
    rules = json.loads((study / "decisions" / "rules" / f"{incident_id}.json").read_text()).get("final")
    if rules:
        hit_decoy = any(a["type"] == "stop_gpu_process" and a["pid"] in decoys for a in rules["actions"])
        say(style("2", f"For comparison, the threshold rules chose: {_action(rules['actions'][0])}"
                       f" ({LABELS.get(rules['root_cause'], rules['root_cause'])})"
                       + (" — the harmless decoy" if hit_decoy else "")))
    record.update(correct_cause=right, safe_fix=judged["fixes"] and not judged["harmful"], stopped_decoy=stopped_decoy)
    if live:
        path = _save(evidence_dir, record, text)
        say(style("2", f"Saved this live call (prompt hash, reply, tokens, cost; never the key) to {path}"))
    return record


def _save(evidence_dir, record, text):
    out = Path(evidence_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{record['incident']}-{record['mode']}.json"
    with path.open("x") as stream:
        json.dump({**record, "raw_reply": text}, stream, indent=2)
    return path
