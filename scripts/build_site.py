#!/usr/bin/env python3
"""Build docs/index.html: the public ServeDoctor results page and live-repair replay.

Everything on the page comes from the committed result packages, re-scored with
the same code the CLI uses. The page is static: no API calls, no external
scripts. Run from the repository root:

    python3 scripts/build_site.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from servedoctor.observe import buckets  # noqa: E402
from servedoctor.scoring import score_study  # noqa: E402
from servedoctor.telemetry import read_jsonl  # noqa: E402

V0 = ROOT / "results" / "servedoctor-20261102"
HARD = ROOT / "results" / "servedoctor-hard-20261103" / "analysis"
TEMPLATE = ROOT / "scripts" / "site_template.html"
OUT = ROOT / "docs" / "index.html"

ARM_ORDER = ["glimmer", "spark", "wonder", "glimmer_to_spark", "glimmer_to_wonder", "rules"]
ARM_LABELS = {"rules": "Threshold rules", "glimmer": "Glimmer alone (local)", "spark": "Spark alone",
              "wonder": "Wonder alone", "glimmer_to_spark": "Glimmer → Spark",
              "glimmer_to_wonder": "Glimmer → Wonder"}
VARIANTS = {
    "surge-near-threshold": "Traffic surge, just over capacity",
    "long-prompt-near-threshold": "Long prompts (15%), decoy job present",
    "batch-near-threshold": "Batch limit 24 (never breached the SLO)",
    "context-near-threshold": "Context limit 1,408 tokens",
    "contention-near-threshold": "GPU contention at 60% duty",
    "surge-plus-contention": "Traffic surge + GPU contention",
    "long-prompt-plus-contention": "Long prompts + GPU contention, decoy present",
    "batch-plus-context": "Batch limit + context limit",
    "kv-plus-context": "KV-cache starvation + context limit",
    "healthy-with-decoy-and-config-noise": "Healthy, decoy job + config noise",
    "healthy-with-burst-and-herring": "Healthy, traffic burst + red herring",
    "healthy-with-lower-memory-setting": "Healthy, lower memory setting",
    "surge-with-decoy": "Traffic surge, decoy job present",
    "underutilization-with-decoy": "Underused GPU, decoy job present",
    "batch-with-noise": "Batch limit 12, decoy + noise",
}


def _board(by_arm):
    rows = []
    for arm in ARM_ORDER:
        if arm in by_arm:
            a = by_arm[arm]
            rows.append({"arm": arm, "label": ARM_LABELS[arm], **{k: a[k] for k in (
                "incidents", "healthy_controls", "detected", "false_alarms", "diagnosis_correct",
                "fix_proposed", "complete_fix", "compound_incidents", "compound_complete_fix", "harmful",
                "stopped_decoy", "invalid_outputs", "api_calls", "api_cost_usd")}})
    return rows


def _decision_view(decision):
    if not decision:
        return None
    return {"root_cause": decision.get("root_cause"), "confidence": decision.get("confidence"),
            "evidence": [str(e)[:220] for e in (decision.get("evidence") or [])][:5],
            "explanation": str(decision.get("explanation") or "")[:500],
            "actions": decision.get("actions") or []}


def live_runs():
    answers = {a["id"]: a for a in json.loads((V0 / "answers" / "answer_keys.json").read_text())["answers"]}
    runs = []
    for path in sorted((V0 / "live").iterdir()):
        result = json.loads((path / "live_result.json").read_text())
        public = json.loads((path / "scenario_public.json").read_text())
        answer = answers[result["id"]]
        series = []
        for b in buckets(read_jsonl(path / "telemetry.jsonl"), float("inf")):
            failed = sum((b["errors"] or {}).values())
            series.append({"t": b["t_end"], "p95": b["p95_latency_s"], "err": round(failed / 10, 2),
                           "queue": b["waiting_max"], "shed": b["shed_rps"], "ok": b["ok_rps"],
                           "arr": b["arrivals_rps"]})
        checkpoints = []
        for row in read_jsonl(path / "checkpoints.jsonl"):
            monitor = row.get("monitor") or {}
            decision = row.get("decision") or {}
            checkpoints.append({
                "t": row["t"], "monitor": monitor.get("status"), "summary": str(monitor.get("summary") or "")[:300],
                "escalated": bool(row.get("escalated")),
                "incident": bool(decision.get("incident")),
                "diagnosis": _decision_view(decision) if decision.get("incident") else None})
        post = result.get("post_fix_window") or {}
        runs.append({
            "id": result["id"], "arm": result["arm"], "cause": answer["root_cause"], "onset": answer["onset_s"],
            "duration": public["duration_s"], "slo": public["slo"],
            "decision_t": (result.get("decision") or {}).get("t"),
            "decision": _decision_view(result.get("decision")),
            "executed": [{"action": e["action"], "status": e.get("status")} for e in result.get("executed", [])],
            "acted_at": result.get("acted_at_s"), "recovered": result.get("recovered"),
            "rolled_back": result.get("rolled_back"), "ttr": result.get("time_to_recover_s"),
            "restart_s": [round(r.get("seconds", 0), 1) for r in result.get("engine_restarts", [])],
            "post": {k: post.get(k) for k in ("requests", "p95_latency_s", "error_rate", "shed_rate")},
            "series": series, "checkpoints": checkpoints})
    return runs


def hard_cases():
    answers = {a["id"]: a for a in json.loads((HARD / "answers" / "answer_keys.json").read_text())["answers"]}
    validity = {r["id"]: r for r in json.loads((HARD / "answers" / "validity.json").read_text())["incidents"]}
    scored = score_study(HARD, split="hard")
    cases = {}
    for row in scored["rows"]:
        answer = answers[row["incident"]]
        case = cases.setdefault(row["incident"], {
            "id": row["incident"], "variant": VARIANTS.get(answer.get("variant"), answer.get("variant")),
            "causes": answer.get("root_causes") or [answer["root_cause"]],
            "valid": validity[row["incident"]]["valid"],
            "decoy": answer.get("red_herrings", {}).get("decoy", False), "cells": {}})
        case["cells"][row["arm"]] = {
            "predicted": row["predicted"], "flagged": row["flagged"], "diagnosis": row["diagnosis_correct"],
            "fix": row["fix_proposed"], "complete": row["complete_fix"], "harmful": row["harmful"],
            "decoy_stop": row["stopped_decoy"], "false_alarm": row["false_alarm"],
            "actions": row["actions"]}
    order = sorted(cases.values(), key=lambda c: (c["causes"] == ["healthy"], len(c["causes"]) > 1, c["id"]))
    return {"all": _board(scored["by_arm"]),
            "valid": _board(score_study(HARD, split="hard", valid_only=True)["by_arm"]),
            "cases": order, "excluded": "hard-16"}


def main():
    data = {"v0": _board(score_study(V0, split="test")["by_arm"]), "live": live_runs(), "hard": hard_cases(),
            "arm_labels": ARM_LABELS}
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("__DATA__", blob)
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html) // 1024} KiB)")


if __name__ == "__main__":
    main()
