"""Score arm decisions against sealed answer keys.

An arm's first incident decision is final. A flag before a workload fault's
onset, or on a healthy incident, is a false alarm. Fixes and harm are judged by
the catalog's per-cause rules, including the direction of any knob change.
"""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

from .catalog import judge_actions
from .evaluate import expert_of
from .llm import PROVIDERS


def score_one(result, answer, runtime):
    final = result["final"]
    truth = answer["root_cause"]
    onset = answer["onset_s"]
    flagged = final is not None
    row = {"arm": result["arm"], "incident": answer["id"], "split": answer["split"], "truth": truth,
           "severity_index": answer["severity_index"], "flagged": flagged,
           "predicted": final["root_cause"] if flagged else "healthy",
           "flag_t": final["t"] if flagged else None, "checkpoints": result["checkpoints"]}
    early = flagged and onset is not None and final["t"] < onset
    row["false_alarm"] = flagged and (truth == "healthy" or early)
    row["detected"] = flagged and truth != "healthy" and not early
    row["time_to_detect_s"] = final["t"] - onset if row["detected"] else None
    row["diagnosis_correct"] = (row["detected"] and final["root_cause"] == truth) or (truth == "healthy" and not flagged)
    actions = final["actions"] if flagged else [{"type": "no_action"}]
    judged = judge_actions(truth if not early else "healthy", actions, current_config=result["engine_config"],
                           contention_pids=runtime.get("contention_pids", []))
    row["fix_proposed"] = judged["fixes"] and not judged["harmful"] and (row["detected"] or truth == "healthy")
    row["harmful"] = judged["harmful"]
    row["actions"] = actions
    escalations = sum(1 for s in result["trail"] if s.get("escalated"))
    row["escalations"] = escalations
    row["invalid_outputs"] = sum(1 for s in result["trail"]
                                 if (s.get("decision") or {}).get("valid_output") is False
                                 or (s.get("monitor") or {}).get("valid_output") is False)
    row["call_failures"] = sum(1 for s in result["trail"] if s.get("error"))
    expert = expert_of(result["arm"])
    cost, calls = Decimal(0), 0
    if expert:
        spec = PROVIDERS[expert]
        for step in result["trail"]:
            if result["arm"] == expert or step.get("escalated"):
                usage = (step.get("decision") or {}).get("usage") or {}
                if isinstance(usage.get("prompt_tokens"), int) and isinstance(usage.get("completion_tokens"), int):
                    cost += (Decimal(usage["prompt_tokens"]) * spec["input_per_m"]
                             + Decimal(usage["completion_tokens"]) * spec["output_per_m"]) / 10**6
                    calls += 1
    row["api_calls"], row["api_cost_usd"] = calls, float(cost)
    return row


def aggregate(rows):
    by_arm = {}
    for row in rows:
        by_arm.setdefault(row["arm"], []).append(row)
    table = {}
    for arm, items in by_arm.items():
        incidents = [r for r in items if r["truth"] != "healthy"]
        healthy = [r for r in items if r["truth"] == "healthy"]
        detected = [r for r in incidents if r["detected"]]
        ttd = sorted(r["time_to_detect_s"] for r in detected)
        table[arm] = {
            "incidents": len(incidents), "healthy_controls": len(healthy),
            "detected": len(detected),
            "false_alarms": sum(r["false_alarm"] for r in items),
            "healthy_false_alarms": sum(r["false_alarm"] for r in healthy),
            "diagnosis_correct": sum(r["diagnosis_correct"] for r in incidents),
            "fix_proposed": sum(r["fix_proposed"] for r in incidents),
            "harmful": sum(r["harmful"] for r in items),
            "median_time_to_detect_s": ttd[len(ttd) // 2] if ttd else None,
            "invalid_outputs": sum(r["invalid_outputs"] for r in items),
            "call_failures": sum(r["call_failures"] for r in items),
            "api_calls": sum(r["api_calls"] for r in items),
            "api_cost_usd": round(sum(r["api_cost_usd"] for r in items), 4),
        }
    return table


def score_study(study_dir, arms=None, split=None):
    root = Path(study_dir)
    answers = json.loads((root / "answers" / "answer_keys.json").read_text())["answers"]
    rows = []
    for answer in answers:
        if split and answer["split"] != split:
            continue
        runtime_path = root / "answers" / "runtime" / f"{answer['id']}.json"
        runtime = json.loads(runtime_path.read_text()) if runtime_path.exists() else {}
        for arm_dir in sorted((root / "decisions").iterdir()) if (root / "decisions").exists() else []:
            if arms and arm_dir.name not in arms:
                continue
            path = arm_dir / f"{answer['id']}.json"
            if path.exists():
                rows.append(score_one(json.loads(path.read_text()), answer, runtime))
    return {"rows": rows, "by_arm": aggregate(rows)}
