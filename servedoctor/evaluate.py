"""Offline evaluation: replay each recorded incident to every arm at fixed checkpoints.

Every arm sees identical observations built only from data at or before each
checkpoint. An arm's first incident decision is final, as it would be on call.
Completed incident results are kept, so a resumed run only pays for new calls.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import rules
from .catalog import ActionError, validate_action
from .llm import BudgetWarningError, MONITOR_SYSTEM, diagnose_system, normalize_decision, parse_json
from .observe import load_incident, normal_profile, observe, render

EXPERTS = ("spark", "wonder")
ARMS = ("rules", "glimmer", "spark", "wonder", "glimmer_to_spark", "glimmer_to_wonder")


def expert_of(arm):
    """The paid Meta model an arm calls, if any."""
    if arm in EXPERTS:
        return arm
    if arm.startswith("glimmer_to_") and arm[len("glimmer_to_"):] in EXPERTS:
        return arm[len("glimmer_to_"):]
    return None


def _rules_decision(observation):
    raw = rules.decide(observation)
    actions = []
    for action in raw["actions"]:
        try:
            actions.append(validate_action(action, current_config=observation["engine_config"]))
        except ActionError:
            actions.append({"type": "escalate_to_human"})
    return {"incident": raw["incident"], "root_cause": raw["root_cause"], "actions": actions,
            "evidence": [], "explanation": "threshold rules", "rejected_actions": []}


def _model_decision(client, observation, max_tokens=2048):
    text, usage = client.chat(diagnose_system(), render(observation), max_tokens=max_tokens)
    try:
        decision = normalize_decision(parse_json(text), current_config=observation["engine_config"])
        decision["valid_output"] = True
    except (ValueError, json.JSONDecodeError):
        decision = {"incident": False, "root_cause": "healthy", "actions": [{"type": "no_action"}],
                    "valid_output": False, "evidence": [], "explanation": "", "rejected_actions": []}
    decision["raw_output"] = text[:4000]
    decision["usage"] = usage
    return decision


def _monitor(client, observation):
    text, usage = client.chat(MONITOR_SYSTEM, render(observation), max_tokens=600)
    try:
        raw = parse_json(text)
        status = raw.get("status") if raw.get("status") in ("healthy", "anomaly") else None
        summary = str(raw.get("summary", ""))[:200]
    except (ValueError, json.JSONDecodeError, AttributeError):
        status, summary = None, ""
    return {"status": status, "summary": summary, "raw_output": text[:1000], "usage": usage,
            "valid_output": status is not None}


def run_incident(arm, incident, *, profile, reference_config, clients, checkpoint_s, on_step=None):
    duration = incident["recording"]["duration_s"]
    trail = []
    final = None
    t = checkpoint_s

    def snapshot():
        return {"arm": arm, "incident": incident["id"], "engine_config": incident["engine_config"],
                "final": final, "checkpoints": len(trail), "trail": trail}

    while t <= duration + 1e-9 and final is None:
        observation = observe(incident, t, profile=profile, reference_config=reference_config)
        step = {"t": t, "observation_sha256": hashlib.sha256(render(observation).encode()).hexdigest()}
        stopped = None
        try:
            if arm == "rules":
                decision = _rules_decision(observation)
            elif arm in ("glimmer",) + EXPERTS:
                decision = _model_decision(clients[arm], observation)
            elif arm.startswith("glimmer_to_") and expert_of(arm):
                monitor = _monitor(clients["glimmer"], observation)
                step["monitor"] = monitor
                # An unreadable monitor reply escalates: failing safe costs a Spark call, not an outage.
                if monitor["status"] == "healthy":
                    decision = {"incident": False, "root_cause": "healthy", "actions": [{"type": "no_action"}]}
                else:
                    step["escalated"] = True
                    decision = _model_decision(clients[expert_of(arm)], observation)
            else:
                raise ValueError(f"Unknown arm {arm}")
        except Exception as exc:  # Provider/network failure: recorded, never retried silently.
            step["error"] = type(exc).__name__
            decision = {"incident": False, "root_cause": "healthy", "actions": [{"type": "no_action"}],
                        "call_failed": True}
            if isinstance(exc, BudgetWarningError):
                stopped = exc
        step["decision"] = decision
        trail.append(step)
        if decision.get("incident"):
            final = {**decision, "t": t}
        if on_step:
            on_step(snapshot())
        if stopped:
            raise stopped
        for client in clients.values():
            ledger = getattr(client, "ledger", None)
            if ledger is not None:
                ledger.require_below_warning()
        t += checkpoint_s
    return snapshot()


def evaluate(study_dir, arms, *, clients, checkpoint_s=30, ids=None, split=None, answers=None, log=print):
    root = Path(study_dir)
    reference_dir = root / "incidents" / "reference"
    reference = load_incident(reference_dir) if reference_dir.exists() else None
    profile = normal_profile(reference["telemetry"]) if reference else None
    reference_config = reference["engine_config"] if reference else None
    split_of = {a["id"]: a["split"] for a in (answers or [])}
    incident_dirs = sorted(p for p in (root / "incidents").iterdir()
                           if p.is_dir() and p.name != "reference" and (ids is None or p.name in ids)
                           and (split is None or split_of.get(p.name) == split))
    results = []
    for arm in arms:
        out_dir = root / "decisions" / arm
        out_dir.mkdir(parents=True, exist_ok=True)
        for path in incident_dirs:
            out = out_dir / f"{path.name}.json"
            if out.exists():
                results.append(json.loads(out.read_text()))
                continue
            partial = out_dir / f"{path.name}.partial.json"
            if partial.exists():
                raise RuntimeError(f"Incomplete evaluation preserved at {partial}; "
                                   "use a new run directory and record the reason before re-evaluating")
            incident = load_incident(path)

            def journal(result):
                temporary = partial.with_suffix(".tmp")
                temporary.write_text(json.dumps({**result, "incomplete": True}, indent=1) + "\n")
                temporary.replace(partial)

            with partial.open("x") as stream:
                json.dump({"arm": arm, "incident": incident["id"], "incomplete": True, "trail": []}, stream)
            result = run_incident(arm, incident, profile=profile, reference_config=reference_config,
                                  clients=clients, checkpoint_s=checkpoint_s, on_step=journal)
            with out.open("x") as stream:
                json.dump(result, stream, indent=1)
            partial.unlink()
            final = result["final"]
            log(f"{arm} {path.name}: " + (f"{final['root_cause']} at t={final['t']} {final['actions']}"
                                          if final else "no incident flagged"))
            results.append(result)
    return results
