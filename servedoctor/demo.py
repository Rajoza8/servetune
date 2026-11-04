"""Live ServeDoctor diagnoses on recorded incidents, runnable by anyone.

With a Meta Model API key in the environment (`MODEL_API_KEY` or `META_API_KEY`),
`run_demo` sends the agent's observation of one real recorded GPU incident to
Muse Spark (or Muse Wonder) and checks the reply against the sealed answer key;
`run_suite` does the same for every incident of a study, several calls at a
time, and scores the replies with the benchmark's own scoring code. Without a
key both replay the replies the same model gave when the study was evaluated,
and say so. No GPU is needed. The model never sees an answer key: keys are read
only after the replies, to grade them.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import textwrap
import time
import urllib.error

from .catalog import ROOT_CAUSES, judge_actions, judge_compound
from .llm import (LedgerError, Ledger, ModelClient, PermanentAPIError, diagnose_system, normalize_decision,
                  parse_json)
from .observe import load_incident, normal_profile, observe, render
from .scoring import score_one

DEFAULT_STUDY = "results/servedoctor-hard-20261103/analysis"
DEFAULT_INCIDENT = "hard-13"
MODELS = {"spark": ("spark", None, 2048), "wonder": ("wonder", "muse-wonder-1.0", 4096)}
KEY_VARS = ("MODEL_API_KEY", "META_API_KEY")
LABELS = {"healthy": "Healthy", "traffic_surge": "Traffic surge", "long_prompt_flood": "Long-prompt flood",
          "kv_cache_starvation": "KV-cache starvation", "batch_limit_too_low": "Batch limit too low",
          "context_limit_too_small": "Context limit too small", "gpu_contention": "GPU contention",
          "underutilization": "Underused GPU", "other": "Other"}
SHORT = {"healthy": "healthy", "traffic_surge": "surge", "long_prompt_flood": "long prompts",
         "kv_cache_starvation": "KV starvation", "batch_limit_too_low": "batch limit",
         "context_limit_too_small": "context limit", "gpu_contention": "GPU contention",
         "underutilization": "underused GPU", "other": "other"}
DISPLAY = {"spark": "Muse Spark", "wonder": "Muse Wonder"}
RETRY_DELAYS_S = (2, 5)


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
        command = str(proc.get("command"))
        command = command if len(command) <= 64 else command[:63] + "…"
        lines.append(f"GPU process  pid {proc['pid']}  {proc.get('used_mb')} MB  {command}")
    for event in observation.get("change_log") or []:
        lines.append(f"change log   {event['t']:>5.0f}s  {event['text']}")
    return lines


def _recorded_reply(study, incident_id, arm, at):
    path = study / "decisions" / arm / f"{incident_id}.json"
    trail = json.loads(path.read_text())["trail"]
    step = min(trail, key=lambda s: abs(s["t"] - at))
    decision = step.get("decision") or {}
    return decision.get("raw_output") or "", decision.get("usage") or {}, step["t"], path


def _checkpoint(study, incident_id, arm="spark"):
    """The checkpoint at which this model's recorded run decided, else its last checkpoint."""
    path = study / "decisions" / arm / f"{incident_id}.json"
    if not path.exists():
        return 150
    recorded = json.loads(path.read_text())
    if recorded.get("final"):
        return recorded["final"]["t"]
    trail = recorded.get("trail") or []
    return trail[-1]["t"] if trail else 150


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
        at = _checkpoint(study, incident_id, model)
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
                        f"study was evaluated,\n  from {path}"))
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
        say(textwrap.fill(str(item), 100, initial_indent="  • ", subsequent_indent="    "))
    if decision.get("explanation"):
        say(textwrap.fill(str(decision["explanation"]), 100, initial_indent="  ", subsequent_indent="  "))
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


def _describe(exc):
    if isinstance(exc, PermanentAPIError):
        return f"HTTP {exc.http_status}"
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    return type(exc).__name__


def _live_call(spec, ledger, environ, transport, prompt):
    """One diagnosis call with a fresh client; retries rate limits, timeouts and server errors twice."""
    client_name, model_id, max_tokens = spec
    client = ModelClient(client_name, ledger=ledger, model=model_id, environ=environ, transport=transport)
    started = time.monotonic()
    for attempt in range(len(RETRY_DELAYS_S) + 1):
        try:
            text, usage = client.chat(diagnose_system(), prompt, max_tokens=max_tokens)
            return {"text": text, "usage": usage, "elapsed_s": time.monotonic() - started,
                    "cost_usd": float(client.cost_usd), "error": None, "attempts": attempt + 1}
        except LedgerError:
            raise
        except Exception as exc:  # reported per incident; the rest of the run continues
            permanent = isinstance(exc, PermanentAPIError) and exc.http_status != 429
            if permanent or attempt == len(RETRY_DELAYS_S):
                return {"text": "", "usage": {}, "elapsed_s": time.monotonic() - started,
                        "cost_usd": float(client.cost_usd), "error": _describe(exc), "attempts": attempt + 1}
            time.sleep(RETRY_DELAYS_S[attempt])


def _cell(text, width):
    return text if len(text) >= width else text + " " * (width - len(text))


def run_suite(*, study_dir=DEFAULT_STUDY, model="spark", recorded=False, workers=4, environ=None, transport=None,
              out=sys.stdout, color=None, evidence_dir="runs/demo", ledger_path="runs/servedoctor-demo-ledger.json"):
    """Diagnose every incident of a study live, several calls at a time, and score the replies.

    Each incident gets one call, at the checkpoint where the same model's
    recorded run made its decision (or its last checkpoint). Replies are scored with the
    benchmark's own `score_one`, so a live tally is directly comparable with the
    published first-decision scoreboard, though it samples the model afresh.
    """
    environ = os.environ if environ is None else environ
    style = Style(out.isatty() if color is None else color)
    say = lambda text="": print(text, file=out, flush=True)
    mark = lambda ok: style("32", "✓") if ok else style("31", "✗")
    study = Path(study_dir)
    answers = {a["id"]: a for a in json.loads((study / "answers" / "answer_keys.json").read_text())["answers"]}
    ids = sorted(i for i in answers if (study / "incidents" / i).is_dir())
    reference_dir = study / "incidents" / "reference"
    reference = load_incident(reference_dir) if reference_dir.exists() else None
    profile = normal_profile(reference["telemetry"]) if reference else None
    spec = MODELS[model]
    key = next((environ[k] for k in KEY_VARS if environ.get(k)), None)
    live = bool(key) and not recorded
    ledger = None
    if live:
        ledger = Ledger(ledger_path)
        if not Path(ledger_path).exists():
            ledger.initialize()
        model_name = ModelClient(spec[0], ledger=ledger, model=spec[1], environ=environ, transport=transport).spec["model"]
    else:
        model_name = DISPLAY[model]
    label = f"{DISPLAY[model]} ({'live' if live else 'recorded'})"

    jobs = {}
    for incident_id in ids:
        at = _checkpoint(study, incident_id, model)
        observation = observe(load_incident(study / "incidents" / incident_id), at, profile=profile,
                              reference_config=reference["engine_config"] if reference else None)
        jobs[incident_id] = {"at": at, "observation": observation, "prompt": render(observation)}

    faulty = [i for i in ids if (answers[i].get("root_causes") or [answers[i]["root_cause"]]) != ["healthy"]]
    name = study.parent.name if study.name == "analysis" else study.name
    say(style("1", f"ServeDoctor · {len(ids)} recorded GPU incidents from {name} "
                   f"({len(faulty)} faults, {len(ids) - len(faulty)} healthy controls)"))
    if live:
        say(style("1;36", f"→ Sending {len(ids)} snapshots to {model_name} on the Meta Model API (live), "
                          f"{workers} at a time. The answer keys stay sealed until each reply is back."))
    else:
        reason = "--recorded was given" if recorded else "no MODEL_API_KEY is set"
        say(style("33", f"→ Recorded mode ({reason}): replaying the replies {model_name} gave when the study was "
                        "evaluated."))
    say()
    say(style("2", f"{'':<39}{label:<31}threshold rules"))
    say(style("2", f"{'incident':<9}{'sealed answer':<30}{'diagnosis':<17}{'fix':<8}{'secs':<6}diagnosis        fix"))

    def fix_cell(row):
        if row["stopped_decoy"]:
            return style("31", "✗ decoy"), 7
        if row["harmful"]:
            return style("31", "✗ harm"), 6
        if row["fix_proposed"] and row["truth"] != "healthy":
            return style("32", "✓ safe"), 6
        return "–", 1

    def finish(incident_id, reply):
        job, answer = jobs[incident_id], answers[incident_id]
        runtime_path = study / "answers" / "runtime" / f"{incident_id}.json"
        runtime = json.loads(runtime_path.read_text()) if runtime_path.exists() else {}
        try:
            decision = normalize_decision(parse_json(reply["text"]), current_config=job["observation"]["engine_config"])
        except (ValueError, json.JSONDecodeError):
            decision = None
        final = ({"root_cause": decision["root_cause"], "actions": decision["actions"], "t": job["at"]}
                 if decision and decision["incident"] else None)
        row = score_one({"arm": model, "final": final, "engine_config": job["observation"]["engine_config"],
                         "checkpoints": 1, "trail": [{"t": job["at"], "decision": {"usage": reply["usage"]}}]},
                        answer, runtime)
        rules = json.loads((study / "decisions" / "rules" / f"{incident_id}.json").read_text())
        rules_row = score_one(rules, answer, runtime)
        causes = answer.get("root_causes") or [answer["root_cause"]]
        truth = " + ".join(SHORT.get(c, c) for c in causes)
        if reply["error"]:
            said, ok = f"error ({reply['error']})", False
        elif decision is None:
            said, ok = "invalid reply", False
        else:
            said, ok = SHORT.get(row["predicted"], row["predicted"]), row["diagnosis_correct"]
        fix, fix_len = fix_cell(row) if decision else ("–", 1)
        rfix, rfix_len = fix_cell(rules_row)
        rsaid = SHORT.get(rules_row["predicted"], rules_row["predicted"])
        secs = f"{reply['elapsed_s']:.1f}" if live else "–"
        say(f"{incident_id:<9}{_cell(truth, 30)}{mark(ok)} {_cell(said, 15)}{fix}{' ' * (8 - fix_len)}"
            f"{secs:<6}{mark(rules_row['diagnosis_correct'])} {_cell(rsaid, 15)}{rfix}")
        return {"incident": incident_id, "at_s": job["at"],
                "prompt_sha256": hashlib.sha256(job["prompt"].encode()).hexdigest(),
                "raw_reply": reply["text"], "usage": reply["usage"], "cost_usd": reply["cost_usd"],
                "elapsed_s": round(reply["elapsed_s"], 2), "attempts": reply.get("attempts"), "error": reply["error"],
                "decision": final, "score": {k: row[k] for k in ("truth", "predicted", "diagnosis_correct",
                                                                 "fix_proposed", "complete_fix", "harmful",
                                                                 "stopped_decoy", "false_alarm")},
                "rules_score": {k: rules_row[k] for k in ("truth", "predicted", "diagnosis_correct", "fix_proposed",
                                                          "harmful", "stopped_decoy", "false_alarm")}}

    started_at = datetime.now(timezone.utc).isoformat()
    records = []
    if live:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(_live_call, spec, ledger, environ, transport, jobs[i]["prompt"]): i for i in ids}
            for future in as_completed(futures):
                records.append(finish(futures[future], future.result()))
    else:
        for incident_id in ids:
            text, usage, _, _ = _recorded_reply(study, incident_id, model, jobs[incident_id]["at"])
            records.append(finish(incident_id, {"text": text, "usage": usage, "elapsed_s": 0.0, "cost_usd": 0.0,
                                                "error": None}))

    def tally(key):
        rows = [r[key] for r in records]
        faults = [r for r in rows if r["truth"] != "healthy"]
        harmful = sum(r["harmful"] for r in rows)
        decoys = sum(r["stopped_decoy"] for r in rows)
        return {"faults": len(faults), "diagnosed": sum(r["diagnosis_correct"] for r in faults),
                "safe_fixes": sum(r["fix_proposed"] for r in faults), "harmful": harmful, "stopped_decoy": decoys,
                "false_alarms": sum(r["false_alarm"] for r in rows)}

    agent, rules = tally("score"), tally("rules_score")
    say()
    cost = sum(r["cost_usd"] for r in records)
    errors = sum(1 for r in records if r["error"])
    timing = (f" · median {statistics.median(r['elapsed_s'] for r in records):.1f} s per call · ${cost:.2f} for "
              f"{len(records)} calls" if live else "")
    say(style("2", "decoy = stopped a harmless GPU job that only looked like the culprit"))
    say()
    say(style("1", f"{label}: {agent['diagnosed']}/{agent['faults']} faults diagnosed · "
                   f"{agent['safe_fixes']} safe fixes · {agent['harmful']} harmful actions · "
                   f"{agent['false_alarms']} false alarms") + timing + (f" · {errors} failed calls" if errors else ""))
    say(f"Threshold rules: {rules['diagnosed']}/{rules['faults']} faults diagnosed · {rules['safe_fixes']} safe fixes · "
        f"{rules['harmful']} harmful actions ({rules['stopped_decoy']} stopped a decoy) · "
        f"{rules['false_alarms']} false alarms")
    say(style("2", "One call per incident, at the checkpoint where this model's recorded run decided."))
    say(style("2", "The published scoreboard scores each agent's first decision over every 30-second checkpoint."))
    summary = {"mode": "live" if live else "recorded", "model": model_name, "study": str(study),
               "started_at_utc": started_at, "workers": workers, "agent": agent, "rules": rules,
               "cost_usd": cost, "failed_calls": errors, "incidents": sorted(records, key=lambda r: r["incident"])}
    if live:
        out_dir = Path(evidence_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-suite-live.json"
        with path.open("x") as stream:
            json.dump(summary, stream, indent=2)
        say(style("2", f"Saved every prompt hash, reply, token count and cost (never the key) to {path}"))
        summary["evidence"] = str(path)
    return summary
