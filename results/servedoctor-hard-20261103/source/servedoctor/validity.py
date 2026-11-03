"""Predeclared symptom check, run on recordings before any arm is scored.

A fault incident is valid only if its requests show an SLO breach in at least
one 30-second window after onset; a healthy or underutilization incident is
valid only if no window breaches. It reads requests, the SLO and the answer
key's onset, never any arm output, so it cannot be tuned toward a model.
"""
from __future__ import annotations

import json
from pathlib import Path

from servetune.artifacts import timestamp

from .loadgen import summarize

RULE = ("fault incidents: >=1 30-s window (by scheduled arrival, from onset) with successful-request p95 "
        "above the SLO or admitted error rate above the SLO; healthy and underutilization incidents: no "
        "such window anywhere")


def breach_windows(requests, slo, start, end, window=30):
    out, t = [], start
    while t < end:
        s = summarize(requests, t, t + window)
        breach = ((s["p95_latency_s"] or 0) > slo["p95_latency_s"]) or s["error_rate"] > slo["max_error_rate"]
        out.append({"start_s": t, "requests": s["requests"], "p95_latency_s": s["p95_latency_s"],
                    "error_rate": round(s["error_rate"], 4), "breach": breach})
        t += window
    return out


def check_incident(incident_dir, answer):
    root = Path(incident_dir)
    recording = json.loads((root / "recording.json").read_text())
    if recording.get("status") == "failed":
        return {"id": answer["id"], "valid": False, "reason": "failed recording"}
    slo = json.loads((root / "slo.json").read_text())
    requests = [json.loads(line) for line in (root / "requests.jsonl").read_text().splitlines() if line.strip()]
    duration = recording["duration_s"]
    causes = answer.get("root_causes") or [answer["root_cause"]]
    quiet = causes in (["healthy"], ["underutilization"])
    start = 0 if quiet or answer["onset_s"] is None else answer["onset_s"]
    windows = breach_windows(requests, slo, start, duration)
    breaches = sum(w["breach"] for w in windows)
    valid = breaches == 0 if quiet else breaches >= 1
    return {"id": answer["id"], "valid": valid, "breach_windows": breaches, "windows": len(windows),
            "reason": None if valid else ("unexpected SLO breach" if quiet else "no observable SLO breach")}


def validate_study(study_dir):
    root = Path(study_dir)
    answers = json.loads((root / "answers" / "answer_keys.json").read_text())["answers"]
    rows = [check_incident(root / "incidents" / a["id"], a) for a in answers
            if (root / "incidents" / a["id"]).exists()]
    result = {"created_at": timestamp(), "rule": RULE, "incidents": rows,
              "valid": sum(r["valid"] for r in rows), "total": len(rows)}
    path = root / "answers" / "validity.json"
    with path.open("x") as stream:  # Never silently rewrite a predeclared verdict.
        json.dump(result, stream, indent=2)
    return result
