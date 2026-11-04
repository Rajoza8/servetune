"""Check the live-demo call records in results/live-demo-20261104.

Every recorded prompt hash must reproduce from the committed incidents and the
current observation code, and every raw model reply must re-score, with the
benchmark's own scoring code, to the scores and tallies stored in the record.

  python3 scripts/verify_live_demo.py [records_dir]
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from servedoctor.llm import normalize_decision, parse_json  # noqa: E402
from servedoctor.observe import load_incident, normal_profile, observe, render  # noqa: E402
from servedoctor.scoring import score_one  # noqa: E402

STUDY = ROOT / "results" / "servedoctor-hard-20261103" / "analysis"
SCORE_KEYS = ("truth", "predicted", "diagnosis_correct", "fix_proposed", "complete_fix", "harmful", "stopped_decoy",
              "false_alarm")


def verify(records_dir=ROOT / "results" / "live-demo-20261104"):
    reference = load_incident(STUDY / "incidents" / "reference")
    profile = normal_profile(reference["telemetry"])
    answers = {a["id"]: a for a in json.loads((STUDY / "answers" / "answer_keys.json").read_text())["answers"]}
    observations, problems, checked = {}, [], 0

    def observation(incident, at):
        if (incident, at) not in observations:
            observations[incident, at] = observe(load_incident(STUDY / "incidents" / incident), at, profile=profile,
                                                 reference_config=reference["engine_config"])
        return observations[incident, at]

    for path in sorted(Path(records_dir).glob("*.json")):
        record = json.loads(path.read_text())
        items = record["incidents"] if "incidents" in record else [record]
        for item in items:
            checked += 1
            obs = observation(item["incident"], item["at_s"])
            if hashlib.sha256(render(obs).encode()).hexdigest() != item["prompt_sha256"]:
                problems.append(f"{path.name} {item['incident']}: prompt hash does not reproduce")
            if "score" not in item:
                continue
            runtime_path = STUDY / "answers" / "runtime" / f"{item['incident']}.json"
            runtime = json.loads(runtime_path.read_text()) if runtime_path.exists() else {}
            try:
                decision = normalize_decision(parse_json(item["raw_reply"]), current_config=obs["engine_config"])
            except (ValueError, json.JSONDecodeError):
                decision = None
            final = ({"root_cause": decision["root_cause"], "actions": decision["actions"], "t": item["at_s"]}
                     if decision and decision["incident"] else None)
            row = score_one({"arm": "spark", "final": final, "engine_config": obs["engine_config"], "checkpoints": 1,
                             "trail": [{"t": item["at_s"], "decision": {"usage": item["usage"]}}]},
                            answers[item["incident"]], runtime)
            if {k: row[k] for k in SCORE_KEYS} != {k: item["score"][k] for k in SCORE_KEYS}:
                problems.append(f"{path.name} {item['incident']}: reply does not re-score to the stored score")
        if "incidents" in record:
            faults = [i["score"] for i in items if i["score"]["truth"] != "healthy"]
            if sum(s["diagnosis_correct"] for s in faults) != record["agent"]["diagnosed"] \
                    or sum(i["score"]["harmful"] for i in items) != record["agent"]["harmful"]:
                problems.append(f"{path.name}: stored tally does not match its rows")
    return checked, problems


if __name__ == "__main__":
    checked, problems = verify(*sys.argv[1:2])
    for problem in problems:
        print("FAIL", problem)
    print(f"{checked} live calls checked: {'all prompts reproduce and all replies re-score' if not problems else f'{len(problems)} problems'}")
    sys.exit(1 if problems else 0)
