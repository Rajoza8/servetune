"""Offline study verification, exports and a standalone evidence dashboard.

No serving, GPU, provider or rental modules are imported. A mutable checkpoint
can be inspected, but only root-sealed live confirmation trials reach headline
tables. Failed, incomplete and synthetic observations remain visible separately.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import statistics
import tempfile

from .quality import evaluate_gate


_PHASES = {"energy_map": "map", "map": "map", "fp8_ab": "ab", "ab": "ab",
           "a/b": "ab", "search": "search", "tuning": "search",
           "confirmation": "confirmation", "final_confirmation": "confirmation"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = ("id", "path", "phase", "arm", "load_label", "config_label", "mode", "status",
           "verified", "eligible", "final_quality_passed", "dtype", "config_sha256", "gpu_uuid", "trace_sha256",
           "joules", "generated_tokens", "completed_requests", "scheduled_requests",
           "joules_per_output_token", "joules_per_completed_request", "p95_latency_s",
           "p95_ttft_s", "output_tokens_per_second", "allocated_seconds", "quality_correct",
           "quality_items", "quality_failed_requests", "quality_threshold", "quality_passed",
           "length_drift_flagged", "length_drift_eligible", "accepted", "decision_reason", "hypothesis")


class StudyVerificationError(ValueError):
    pass


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                       allow_nan=False) + "\n").encode()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StudyVerificationError("Duplicate JSON object key")
        result[key] = value
    return result


def _load(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 25_000_000:
        raise StudyVerificationError("Expected bounded regular JSON evidence")
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=_unique,
                           parse_constant=lambda value: (_ for _ in ()).throw(
                               StudyVerificationError("Nonfinite JSON evidence")))
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise StudyVerificationError("Invalid finite unique-key JSON evidence") from exc


def _safe_path(root, value):
    if type(value) is not str or "\\" in value:
        raise StudyVerificationError("Evidence paths must be relative POSIX strings")
    relative = PurePosixPath(value)
    if (relative.is_absolute() or not relative.parts or ".." in relative.parts
            or value in {"", "."}):
        raise StudyVerificationError("Evidence path is absolute or traverses outside its root")
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise StudyVerificationError("Evidence path escapes its root")
    current = path
    while current != root:
        if current.is_symlink():
            raise StudyVerificationError("Evidence symlinks are forbidden")
        current = current.parent
    return path


def _files(root):
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise StudyVerificationError("Evidence contains a symlink")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path
    return result


def _verify_manifest(root):
    manifest = _load(root / "manifest.json")
    if type(manifest) is not dict or type(manifest.get("files")) is not dict:
        raise StudyVerificationError("Missing or malformed evidence manifest")
    recorded = manifest["files"]
    found = _files(root)
    found.pop("manifest.json", None)
    if set(found) != set(recorded):
        raise StudyVerificationError("Evidence files were added or removed after sealing")
    for name, record in recorded.items():
        path = _safe_path(root, name)
        checksum = record.get("sha256") if type(record) is dict else record
        if type(checksum) is not str or not _HASH.fullmatch(checksum):
            raise StudyVerificationError("Invalid SHA256 manifest entry")
        if _hash(path.read_bytes()) != checksum:
            raise StudyVerificationError(f"Evidence hash mismatch: {name}")
        if type(record) is dict and "bytes" in record and record["bytes"] != path.stat().st_size:
            raise StudyVerificationError("Manifest byte count differs")
    return _hash((root / "manifest.json").read_bytes())


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _phase(value):
    return _PHASES.get(str(value).casefold().replace("-", "_"), str(value or "unknown"))


def _first_number(value, names):
    if type(value) is dict:
        for key, item in value.items():
            if key in names and _number(item) is not None:
                return item
        for item in value.values():
            found = _first_number(item, names)
            if found is not None:
                return found
    return None


def _row(index, trial, *, verified):
    measurement = trial.get("measurement") or {}
    quality = trial.get("quality") or index.get("quality_summary") or {}
    gate = trial.get("quality_gate") or index.get("quality_gate") or {}
    hardware = trial.get("hardware") or {}
    gpu = hardware.get("gpu") or hardware
    decision = index.get("decision", trial.get("decision"))
    if type(decision) is dict:
        accepted = decision.get("accepted", decision.get("keep"))
        reason = decision.get("reason", "; ".join(str(value) for value in decision.get("reasons", [])))
    else:
        accepted = True if isinstance(decision, str) and decision in {"accept", "accepted", "keep"} else (
            False if isinstance(decision, str) and decision in {"reject", "rejected", "revert"} else None)
        reason = decision or ""
    proposal = index.get("proposal", trial.get("proposal")) or {}
    drift = index.get("length_drift", trial.get("length_drift")) or {}
    proposal = proposal if isinstance(proposal, dict) else {}
    drift = drift if isinstance(drift, dict) else {}
    result = {key: index.get(key) for key in ("id", "path", "arm", "load_label", "config_label")}
    result.update(phase=_phase(index.get("phase", trial.get("phase"))),
                  mode=trial.get("mode", "unknown"), status=trial.get("status", "unknown"),
                  verified=verified, dtype=trial.get("dtype"), config_sha256=trial.get("config_sha256"),
                  gpu_uuid=gpu.get("uuid", trial.get("gpu_uuid")), trace_sha256=trial.get("trace_sha256"),
                  allocated_seconds=_number(trial.get("allocated_seconds")),
                  quality_correct=quality.get("correct"), quality_items=quality.get("items"),
                  quality_failed_requests=quality.get("failed_requests"),
                  quality_threshold=gate.get("minimum_correct"), quality_passed=gate.get("passed"),
                  length_drift_flagged=drift.get("flagged", index.get("length_drift_flagged")),
                  length_drift_eligible=drift.get("eligible"),
                  accepted=accepted, decision_reason=str(reason),
                  hypothesis=str(index.get("hypothesis", trial.get("hypothesis", proposal.get("hypothesis", "")))))
    for name in ("joules", "generated_tokens", "completed_requests", "scheduled_requests",
                 "joules_per_output_token", "joules_per_completed_request", "p95_latency_s",
                 "p95_ttft_s", "output_tokens_per_second"):
        result[name] = _number(measurement.get(name))
    result["all_requests_completed"] = measurement.get("all_requests_completed")
    result["arrival_rate"] = _number(index.get("arrival_rate", trial.get("arrival_rate")))
    result["live_observation"] = bool(verified and result["mode"] == "live")
    result["eligible"] = bool(result["live_observation"] and result["status"] == "pass"
                              and measurement.get("all_requests_completed") is True
                              and gate.get("passed") is not False
                              and quality.get("failed_requests", 0) == 0
                              and result["length_drift_eligible"] is not False)
    energy = measurement.get("energy") or {}
    samples = energy.get("samples") or []
    valid_power = [sample for sample in samples if type(sample) is dict
                   and _number(sample.get("monotonic_s")) is not None
                   and _number(sample.get("power_w")) is not None]
    if valid_power:
        start = valid_power[0]["monotonic_s"]
        step = max(1, math.ceil(len(valid_power) / 400))
        result["power_samples"] = [{"t": sample["monotonic_s"] - start, "w": sample["power_w"]}
                                   for sample in valid_power[::step]]
    else:
        result["power_samples"] = []
    return result


def verify_study(study_dir):
    """Verify every sealed indexed trial; identify unsealed checkpoints honestly.

    A missing final study manifest is an inspectable partial snapshot, not a
    headline-ready study. A present but invalid manifest always raises.
    """
    supplied = Path(study_dir)
    if supplied.is_symlink() or not supplied.is_dir():
        raise StudyVerificationError("Study must be a regular existing directory")
    root = supplied.resolve()
    _files(root)  # Reject symlinks even in metadata or pending trial directories.
    root_hash = _verify_manifest(root) if (root / "manifest.json").exists() else None
    study = _load(root / "study.json", {})
    state = _load(root / "state.json", {})
    if type(study) is not dict or type(state) is not dict:
        raise StudyVerificationError("Study/state metadata must be objects")
    index = study.get("trials", state.get("trials", []))
    if type(index) is not list:
        raise StudyVerificationError("Study trial index must be a list")
    histories, timeline = {}, []
    for arm in ("R", "S"):
        history = _load(root / "arms" / arm / "history.json", [])
        if type(history) is not list:
            raise StudyVerificationError("Arm histories must be lists")
        for item in history:
            if type(item) is not dict or type(item.get("trial")) is not int or item["trial"] < 0:
                raise StudyVerificationError("Arm history entries require nonnegative trial indices")
            identifier = f"search-{arm}-{item['trial']:03d}"
            decision = item.get("decision") or {}
            proposal = item.get("proposal") or {}
            if type(decision) is not dict or type(proposal) is not dict:
                raise StudyVerificationError("Arm decision/proposal records must be objects")
            histories[identifier] = item
            timeline.append({"id": identifier, "phase": "search", "arm": arm,
                "mode": study.get("mode", state.get("mode", "unknown")),
                "hypothesis": str(proposal.get("hypothesis", "")), "accepted": decision.get("accepted"),
                "decision_reason": decision.get("reason", "; ".join(str(value) for value in decision.get("reasons", []))),
                "planner_wait_seconds": _number(item.get("planner_wait_seconds")),
                "allocated_seconds": _number(item.get("allocated_seconds")),
                "length_drift_flagged": (decision.get("length_drift") or {}).get("flagged"),
                "started_at": item.get("started_at"), "ended_at": item.get("ended_at")})
    warnings = []
    if root_hash is None:
        warnings.append("Study root is not sealed; checkpoint metadata is provisional and no headline is published")
    seen_ids, seen_paths, rows, records = set(), set(), [], {}
    for entry in index:
        if type(entry) is not dict or type(entry.get("id")) is not str or not entry["id"]:
            raise StudyVerificationError("Each trial index entry needs a unique ID")
        trial_path = _safe_path(root, entry.get("path", ""))
        directory = trial_path.parent if trial_path.name == "trial.json" else trial_path
        if not directory.is_relative_to(root / "trials"):
            raise StudyVerificationError("Trial index must reference project trial directories")
        relative = directory.relative_to(root).as_posix()
        if entry["id"] in seen_ids or relative in seen_paths:
            raise StudyVerificationError("Duplicate trial ID or evidence directory")
        seen_ids.add(entry["id"])
        seen_paths.add(relative)
        normalized = {**entry, "path": relative}
        if _phase(entry.get("phase")) == "search":
            history = histories.get(entry.get("config_label"))
            if history:
                decision = history.get("decision") or {}
                normalized = {**normalized, "proposal": history.get("proposal"),
                              "decision": decision, "length_drift": decision.get("length_drift"),
                              "quality_gate": history.get("quality_gate")}
        if not (directory / "manifest.json").exists():
            warnings.append(f"Trial {entry['id']} is unsealed/incomplete; excluded from measurements")
            rows.append(_row(normalized, {"status": "unsealed", "mode": "unknown"}, verified=False))
            continue
        _verify_manifest(directory)
        trial = _load(directory / "trial.json")
        if type(trial) is not dict:
            raise StudyVerificationError("Sealed trial.json must be an object")
        if trial.get("config_sha256") and trial.get("config") is not None:
            encoded = json.dumps(trial["config"], sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode()
            if trial["config_sha256"] != _hash(encoded):
                raise StudyVerificationError("Trial config hash disagrees with config")
        measurement = trial.get("measurement") or {}
        if trial.get("trace_sha256"):
            trace = _load(directory / "trace.json")
            if trace is None or _hash(json.dumps(trace, sort_keys=True, ensure_ascii=False,
                                                 separators=(",", ":"), allow_nan=False).encode()) != trial["trace_sha256"]:
                raise StudyVerificationError("Trial trace hash disagrees with its frozen trace file")
        if (measurement.get("trace_sha256") and trial.get("trace_sha256")
                and measurement["trace_sha256"] != trial["trace_sha256"]):
            raise StudyVerificationError("Trial and measurement trace hashes disagree")
        rows.append(_row(normalized, trial, verified=True))
        records[entry["id"]] = trial
    for candidate in sorted((root / "trials").glob("*/trial.json")):
        relative = candidate.parent.relative_to(root).as_posix()
        if relative not in seen_paths:
            warnings.append(f"Unindexed trial evidence retained at {relative}; excluded until the orchestration index records it")
    protocol = _load(root / "protocol.json", {})
    confirmation = _load(root / "confirmation.json", {})
    frozen = _load(root / "frozen.json", {})
    if type(protocol) is not dict or type(confirmation) is not dict:
        raise StudyVerificationError("Protocol/confirmation metadata must be objects")
    if type(frozen) is not dict:
        raise StudyVerificationError("Frozen workload metadata must be an object")
    if study.get("protocol_sha256") and study["protocol_sha256"] != _hash(json.dumps(
            protocol, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()):
        raise StudyVerificationError("Study protocol hash disagrees with frozen protocol")
    load_lookup = {item["label"]: item for item in frozen.get("loads", [])
                   if type(item) is dict and isinstance(item.get("label"), str)}
    for row in rows:
        load = load_lookup.get(row["load_label"])
        if load:
            row["arrival_rate"] = _number(load.get("arrival_rate"))
            if row["verified"] and load.get("trace_sha256") and row["trace_sha256"] != load["trace_sha256"]:
                raise StudyVerificationError("Trial differs from the frozen load's trace identity")
    for item in timeline:
        linked = next((row for row in rows if row["config_label"] == item["id"]), None)
        item["load_label"] = linked["load_label"] if linked else frozen.get("tuning_load")
    headline = [row for row in rows if root_hash and row["phase"] == "confirmation"
                and row["live_observation"]]
    declared = study.get("floor", {})
    if type(declared) is bool:
        declared = {"built": declared}
    if type(declared) is not dict:
        declared = {}
    claimed = declared.get("built", study.get("floor_built", False)) is True
    maps = [row for row in rows if row["phase"] == "map" and row["live_observation"]
            and row["joules_per_output_token"] is not None]
    fp8_required = declared.get("fp8_required") is True
    fp8_complete = (not fp8_required or
        (any(row["dtype"] == "fp8" for row in maps)
         and all(sum(row["phase"] == "ab" and row["live_observation"] and row["dtype"] == dtype
                     for row in rows) >= 5 for dtype in ("bf16", "fp8"))))
    floor = {"controller_claimed_built": claimed, "live_verified_map_trials": len(maps),
             "established": bool(root_hash and claimed and any(row["dtype"] == "bf16" for row in maps)
                                 and fp8_complete), "conditional_fp8_supported": fp8_complete,
             "reason": str(declared.get("reason", "No completed floor attested by the controller"))}
    if claimed and not floor["established"]:
        warnings.append("Controller floor flag lacks a sealed study with genuine live verified map observations")
    slo = _first_number(protocol, {"latency_slo_s", "p95_latency_slo_s", "p95_slo_s", "slo_seconds", "slo_s"})
    for row in rows:
        if slo is not None and row["p95_latency_s"] is not None and row["p95_latency_s"] > slo:
            row["eligible"] = False
    result = {"schema_version": 1, "study_dir": str(root), "root_manifest_verified": root_hash is not None,
            "root_manifest_sha256": root_hash, "status": study.get("status", state.get("status", "partial")),
            "study": study, "protocol": protocol, "confirmation": confirmation, "frozen": frozen,
            "rows": rows, "records": records, "headline_rows": headline,
            "floor": floor, "latency_slo_s": slo, "timeline": timeline, "warnings": warnings}
    final_pairs, quality_note = _paired(result)
    final_gates = {row["config_label"]: row["passed"] for row in final_pairs}
    for row in headline:
        row["final_quality_passed"] = final_gates.get(row["config_label"] or row["id"])
        row["eligible"] = row["eligible"] and row["final_quality_passed"] is True
    result.update(final_paired_quality=final_pairs, final_quality_note=quality_note)
    return result


def _paired(verified):
    quality = dict(verified["confirmation"].get("quality_results", {}))
    for row in verified["headline_rows"]:
        record = verified["records"][row["id"]]
        score = record.get("quality")
        if type(score) is dict and score.get("items") == 300:
            quality.setdefault(row["config_label"] or row["id"], score)
    baseline_label = verified["confirmation"].get("baseline_label")
    if not baseline_label:
        candidates = [label for label in quality if "bf16" in str(label).casefold()
                      and "default" in str(label).casefold()]
        baseline_label = candidates[0] if len(candidates) == 1 else None
    if not verified["root_manifest_verified"] or not verified["headline_rows"] or baseline_label not in quality:
        return [], "Final paired quality is unavailable: no sealed matched bf16-default final reference"
    rows = []
    try:
        for label, candidate in quality.items():
            rows.append({"config_label": label,
                         **evaluate_gate(candidate, quality[baseline_label], "final")})
    except (ValueError, TypeError, KeyError):
        return [], "Final paired quality failed item/scorer/count validation; no equivalence claim is published"
    return rows, None


def _csv(rows, fields):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        safe = {}
        for key in fields:
            value = row.get(key)
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                value = "'" + value
            safe[key] = value
        writer.writerow(safe)
    return output.getvalue()


def _fmt(value):
    return f"{value:.6g}" if _number(value) is not None else "—"


def _md(value):
    return str(value if value is not None else "—").replace("|", "/").replace("\n", " ").replace("<", "&lt;")


def _pareto(rows):
    usable = [row for row in rows if row["eligible"] and row["p95_latency_s"] is not None
              and row["joules_per_output_token"] is not None]
    return sorted([row for row in usable if not any(
        other["p95_latency_s"] <= row["p95_latency_s"]
        and other["joules_per_output_token"] <= row["joules_per_output_token"]
        and (other["p95_latency_s"] < row["p95_latency_s"]
             or other["joules_per_output_token"] < row["joules_per_output_token"])
        for other in usable)], key=lambda row: row["p95_latency_s"])


def _svg(title, rows, xkey, ykey, xlabel, ylabel, *, slo=None, threshold=None):
    width, height, left, top, right, bottom = 760, 440, 85, 55, 25, 70
    usable = [row for row in rows if _number(row.get(xkey)) is not None and _number(row.get(ykey)) is not None]
    xmax = max([row[xkey] for row in usable] + ([slo] if slo is not None else []) + [1]) * 1.08
    ymax = max([row[ykey] for row in usable] + ([threshold] if threshold is not None else []) + [1]) * 1.12
    x = lambda value: left + value / xmax * (width - left - right)
    y = lambda value: height - bottom - value / ymax * (height - top - bottom)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
             f'<title>{html.escape(title)}</title><rect width="100%" height="100%" fill="white"/>',
             '<g font-family="Arial,sans-serif" fill="#142638">',
             f'<text x="{left}" y="28" font-size="18" font-weight="600">{html.escape(title)}</text>']
    for i in range(6):
        xx, yy = left + (width-left-right)*i/5, top + (height-top-bottom)*i/5
        lines += [f'<path d="M {xx:.2f} {top} V {height-bottom} M {left} {yy:.2f} H {width-right}" stroke="#e5ebf1" fill="none"/>',
                  f'<text x="{xx:.2f}" y="{height-bottom+23}" text-anchor="middle" font-size="11">{xmax*i/5:.3g}</text>',
                  f'<text x="{left-12}" y="{yy+4:.2f}" text-anchor="end" font-size="11">{ymax*(5-i)/5:.3g}</text>']
    if slo is not None:
        lines.append(f'<path d="M {x(slo):.2f} {top} V {height-bottom}" stroke="#c13c45" stroke-dasharray="6 4"/><text x="{x(slo)+5:.2f}" y="{top+14}" font-size="11">Latency SLO</text>')
    if threshold is not None:
        lines.append(f'<path d="M {left} {y(threshold):.2f} H {width-right}" stroke="#c13c45" stroke-dasharray="6 4"/><text x="{left+8}" y="{y(threshold)-7:.2f}" font-size="11">Quality threshold {threshold:g}</text>')
    if xkey == "p95_latency_s" and ykey == "joules_per_output_token":
        front = _pareto(rows)
        if len(front) > 1:
            points = " ".join(f'{x(row[xkey]):.2f},{y(row[ykey]):.2f}' for row in front)
            lines.append(f'<polyline points="{points}" fill="none" stroke="#8e9eb0" stroke-width="2" stroke-dasharray="5 4"/>')
    for row in usable:
        color = "#1c8c72" if row.get("arm") == "R" else "#3567bb" if row.get("arm") == "S" else (
            "#865ac4" if row.get("phase") == "confirmation" else "#d29128" if row.get("dtype") == "fp8" else "#58758c")
        title_text = f"{row['id']}: {row.get('config_label') or row.get('dtype')}; {xlabel}={row[xkey]:.6g}; {ylabel}={row[ykey]:.6g}"
        lines.append(f'<circle cx="{x(row[xkey]):.2f}" cy="{y(row[ykey]):.2f}" r="4.5" fill="{color}" opacity="0.8"><title>{html.escape(title_text)}</title></circle>')
    if not usable:
        lines.append(f'<text x="{width/2}" y="{height/2}" text-anchor="middle" fill="#6c7b88">No recorded observations for this chart</text>')
    lines += [f'<text x="{(left+width-right)/2}" y="{height-17}" text-anchor="middle" font-size="13">{html.escape(xlabel)}</text>',
              f'<text transform="translate(20 {(top+height-bottom)/2}) rotate(-90)" text-anchor="middle" font-size="13">{html.escape(ylabel)}</text>', '</g></svg>']
    return "\n".join(lines)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise StudyVerificationError("Report output may not replace a symlink")
    raw = content if isinstance(content, bytes) else content.encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _markdown(verified, paired, quality_note):
    rows, headline = verified["rows"], verified["headline_rows"]
    lines = ["# ServeTune results", "", f"Recorded study status: **{_md(verified['status'])}**. "
             f"Root manifest verified: **{verified['root_manifest_verified']}**.", "",
             "Energy is GPU energy (NVML), not whole-system energy. Observations apply only to the recorded hardware, engine, model revision and frozen workloads.", "",
             f"Indexed trials: {len(rows)}; verified live observations: {sum(row['live_observation'] for row in rows)}; "
             f"synthetic fixtures: {sum(row['mode'] == 'synthetic_fixture' for row in rows)}.", ""]
    lines += [f"- {_md(warning)}" for warning in verified["warnings"]]
    lines += ["", "## Fresh confirmation only", "",
              "The headline table retains every verified live confirmation attempt from the sealed final study, including failures and ineligible configurations. Tuning measurements and synthetic fixtures do not enter it.", "",
              "| Trial | Config | Load | Status | Eligible | GPU J/token | GPU J/request | p95 latency (s) |", "| --- | --- | --- | --- | --- | ---: | ---: | ---: |"]
    for row in headline:
        lines.append(f"| {_md(row['id'])} | {_md(row['config_label'] or row['dtype'])} | {_md(row['load_label'])} | {_md(row['status'])} | {row['eligible']} | {_fmt(row['joules_per_output_token'])} | {_fmt(row['joules_per_completed_request'])} | {_fmt(row['p95_latency_s'])} |")
    if not headline:
        lines += ["", "No headline result is available. A partial or null experiment remains a valid recorded outcome."]
    lines += ["", "## Final paired quality", ""]
    if quality_note:
        lines.append(quality_note)
    if paired:
        lines += ["| Config | Correct / 300 | Reference correct | Lost | Gained | Difference (pp) | Within 2 pp tolerance |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
        for row in paired:
            lines.append(f"| {_md(row['config_label'])} | {row['candidate_correct']} | {row['reference_correct']} | {row['paired_lost']} | {row['paired_gained']} | {_fmt(row['difference_percentage_points'])} | {row['passed']} |")
        lines += ["", "A count-tolerance pass means **within the predeclared 2-percentage-point tolerance** on these fixed items; it is not statistical equivalence or general absence of regression."]
    lines += ["", "## All process evidence", "", "Failed, incomplete, reverted and synthetic trials remain in [trials.csv](trials.csv). "
              "[headline.csv](headline.csv) is restricted to confirmation. The [offline dashboard](dashboard.html) supports load/phase/arm filters, trial replay and recorded power traces.", "",
              "Quantization is not assumed to improve energy or latency. Observed A/B ranges are descriptive; tuning-time screening margins are not significance tests. "
              "An agent loss or inconclusive comparison must remain visible.", ""]
    budget = verified["study"].get("budget", {})
    lines += ["## Budgets and time", "", "Meta API cap: **$15**; Baseten cap: **$5**. "
              "GPU rentals have a separately authorized **$60 cumulative Vast cap**; this report does not infer provider invoices or remaining rental credit from trial time.", "",
              "| API provider | Accounted USD | Cap USD | Unreconciled USD |", "| --- | ---: | ---: | ---: |"]
    for provider, cap in (("meta", 15), ("baseten", 5)):
        lines.append(f"| {provider} | {_fmt(budget.get('accounted_usd', {}).get(provider))} | {cap} | "
                     f"{_fmt(budget.get('unreconciled_reservations_usd', {}).get(provider))} |")
    lines += ["", "API amounts are retained token-based estimates and unknown-call reservations, not invoices. "
              "Each arm's allocated planning, startup, warmup, measurement, evaluation and failure time must be charged; "
              "the other arm's allocation stays paused. See [decisions.csv](decisions.csv) and the retained arm histories.", ""]
    floor = verified["floor"]
    floor_lines = ["# ServeTune conditional floor", "", f"Controller recorded floor built: **{floor['controller_claimed_built']}**.",
                   f"Verified live map observations: **{floor['live_verified_map_trials']}**.",
                   f"Sealed floor attestation supported: **{floor['established']}**.", "", _md(floor["reason"]), "",
                   "Preflight alone is not an energy map. This report never infers a completed floor from a simulation, an unsealed checkpoint, or an API connectivity check. "
                   "The controller's frozen grid and conditional FP8 requirements determine completeness; inspect protocol.json and all retained map/A/B records.", ""]
    return "\n".join(lines), "\n".join(floor_lines)


def generate_report(study_dir, out_dir=None):
    """Write CSV, Markdown, standalone SVGs and a zero-network HTML dashboard."""
    verified = verify_study(study_dir)
    root = Path(verified["study_dir"])
    out = Path(out_dir).resolve() if out_dir is not None else root.with_name(root.name + "-report")
    if out.is_relative_to(root) or out.is_symlink():
        raise StudyVerificationError("Report output must be outside the evidence study directory")
    out.mkdir(parents=True, exist_ok=True)
    paired, quality_note = _paired(verified)
    results_md, floor_md = _markdown(verified, paired, quality_note)
    rows = verified["rows"]
    _write(out / "trials.csv", _csv(rows, _FIELDS))
    _write(out / "headline.csv", _csv(verified["headline_rows"], _FIELDS))
    _write(out / "decisions.csv", _csv(verified["timeline"], ("id", "arm", "started_at", "ended_at",
        "hypothesis", "accepted", "decision_reason", "length_drift_flagged", "planner_wait_seconds", "allocated_seconds")))
    _write(out / "results.md", results_md)
    _write(out / "floor.md", floor_md)
    _write(out / "verification.json", _json_bytes({key: verified[key] for key in
        ("schema_version", "root_manifest_verified", "root_manifest_sha256", "status", "floor", "warnings")}))
    live = [row for row in rows if row["live_observation"]]
    for load in sorted({str(row["load_label"] or "unspecified") for row in live if row["phase"] == "map"}):
        selected = [row for row in live if row["phase"] == "map" and str(row["load_label"] or "unspecified") == load]
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", load)[:40] + "-" + _hash(load.encode())[:8]
        _write(out / "svg" / f"energy-latency-{slug}.svg", _svg(f"GPU energy / latency · {load}", selected,
               "p95_latency_s", "joules_per_output_token", "p95 end-to-end latency (s)", "GPU J / output token", slo=verified["latency_slo_s"]))
    search = [{**row, "trial_number": i + 1} for i, row in enumerate(live) if row["phase"] == "search"]
    _write(out / "svg/search-energy.svg", _svg("Search observations · R and S", search, "trial_number",
           "joules_per_output_token", "Recorded trial order", "GPU J / output token"))
    _write(out / "svg/search-latency.svg", _svg("Search latency", search, "trial_number", "p95_latency_s",
           "Recorded trial order", "p95 latency (s)", threshold=verified["latency_slo_s"]))
    thresholds = [row["quality_threshold"] for row in rows if _number(row["quality_threshold"]) is not None]
    if not thresholds and _number(verified["frozen"].get("quality_reference_correct")) is not None:
        thresholds = [max(0, verified["frozen"]["quality_reference_correct"] - 3)]
    _write(out / "svg/quality.svg", _svg("Dev quality observations", search, "trial_number", "quality_correct",
           "Recorded trial order", "Correct dev answers", threshold=thresholds[0] if thresholds else None))
    _write(out / "svg/search-request-energy.svg", _svg("Search GPU energy per request", search,
           "trial_number", "joules_per_completed_request", "Recorded trial order", "GPU J / completed request"))
    ab_rows = [{**row, "dtype_index": 1 if row["dtype"] == "bf16" else 2}
               for row in live if row["phase"] == "ab"]
    _write(out / "svg/bf16-fp8-ab.svg", _svg("BF16 / FP8 observed A/B repeats", ab_rows,
           "dtype_index", "joules_per_output_token", "1 = BF16; 2 = FP8", "GPU J / output token"))
    loads = list(dict.fromkeys(str(row["load_label"] or "unspecified") for row in live if row["phase"] == "map"))
    overview = [{**row, "load_index": loads.index(str(row["load_label"] or "unspecified")) + 1}
                for row in live if row["phase"] == "map"]
    _write(out / "svg/energy-load.svg", _svg("GPU energy against recorded load", overview,
           "load_index", "joules_per_output_token", "; ".join(f"{i+1}={label}" for i, label in enumerate(loads)),
           "GPU J / output token"))
    data = {"status": verified["status"], "sealed": verified["root_manifest_verified"],
            "warnings": verified["warnings"], "rows": rows, "headline": verified["headline_rows"],
            "floor": verified["floor"], "slo": verified["latency_slo_s"], "paired_quality": paired,
            "quality_note": quality_note, "quality_threshold": thresholds[0] if thresholds else None,
            "timeline": verified["timeline"],
            "synthetic_only": bool(rows and all(row["mode"] == "synthetic_fixture" for row in rows))}
    embedded = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    _write(out / "dashboard.html", _DASHBOARD.replace("__STUDY_DATA__", embedded))
    paths = {"dashboard": str(out / "dashboard.html"), "results": str(out / "results.md"),
             "floor": str(out / "floor.md"), "trials_csv": str(out / "trials.csv"),
             "headline_csv": str(out / "headline.csv"), "verification": str(out / "verification.json"),
             "decisions_csv": str(out / "decisions.csv"),
             "svg_dir": str(out / "svg")}
    return {"out_dir": str(out), "paths": paths, **paths,
            "root_manifest_verified": verified["root_manifest_verified"],
            "headline_observations": len(verified["headline_rows"]), "warnings": verified["warnings"]}


_DASHBOARD = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ServeTune · evidence replay</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#152b3e;background:#eef3f7}*{box-sizing:border-box}body{margin:0}header{padding:32px max(4vw,20px);background:#10293c;color:white}header p{color:#b9cfdd;max-width:850px;line-height:1.5}h1{font-size:34px;margin:8px 0}h2{font-size:19px;margin:0 0 12px}h3{font-size:15px;margin:0 0 8px}.eyebrow{letter-spacing:.16em;font-size:11px;text-transform:uppercase;color:#75d3be}main{max-width:1500px;margin:auto;padding:24px}.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:16px 0}label{font-size:12px;color:#526b7d}select,button{font:inherit;padding:8px 12px;border:1px solid #c8d6df;border-radius:7px;background:white;color:#163b52}button{cursor:pointer}button:hover{background:#e1f5ef}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:18px}.card{background:white;border:1px solid #dbe5ec;border-radius:12px;padding:20px;overflow:hidden;margin-bottom:18px}.stats{display:flex;gap:16px;flex-wrap:wrap}.stat{min-width:160px}.big{font-size:28px;font-weight:650}.muted{color:#657d8d;font-size:12px;line-height:1.5}.warn{border-left:4px solid #d2932d;background:#fff5de;padding:12px;line-height:1.5}.pill{display:inline-block;padding:3px 7px;border-radius:5px;background:#eaf1f6;font-size:11px}.chart svg{width:100%;height:auto;display:block}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:10px;border-bottom:1px solid #e6edf2;text-align:left;white-space:nowrap}th{color:#526e80}tbody tr{cursor:pointer}tbody tr:hover{background:#eef9f5}.timeline{display:grid;gap:10px}.event{padding:12px;border-left:3px solid #7394ac;background:#f5f8fa;border-radius:5px;font-size:13px;line-height:1.5}.event strong{display:block}.reason{white-space:pre-wrap}.legend{display:flex;gap:15px;font-size:12px;margin:10px 0;color:#526e80}a{color:#24816e}.links{display:flex;gap:14px;flex-wrap:wrap}footer{padding:24px;color:#6b8291;font-size:12px}@media(max-width:500px){.grid{grid-template-columns:1fr}main{padding:12px}}
</style>
<header><div class="eyebrow">ServeTune / measured decisions</div><h1>Efficiency, with the evidence attached.</h1><p>Offline replay of GPU energy, latency and quality observations. Every failed or reverted attempt stays visible. Headline results come only from sealed, live confirmation measurements.</p><div class="links"><a href="results.md">Results</a><a href="floor.md">Conditional floor</a><a href="trials.csv">All trials CSV</a><a href="headline.csv">Confirmation CSV</a></div></header>
<main><div id="notice"></div><section class="card stats" id="stats"></section>
<div class="controls"><label>Phase <select id="phase" aria-label="Phase"></select></label><label>Load <select id="load" aria-label="Load"></select></label><label>Arm <select id="arm" aria-label="Arm"></select></label><label>Evidence <select id="mode" aria-label="Evidence"></select></label><button id="play">Replay trials</button><span class="muted">Local file · no GPU, API keys or network</span></div>
<section class="card"><h2>Energy / latency map</h2><p class="muted">One panel per recorded load. Lower energy and latency dominate; dashed frontier uses only eligible live observations. R green · S blue · FP8 amber · confirmation purple.</p><div class="grid" id="maps"></div></section>
<div class="grid"><section class="card"><h2>Energy against load</h2><div id="overview" class="chart"></div></section><section class="card"><h2>BF16 / FP8 A/B observations</h2><p class="muted">Dots are observed repeats. Lines show median and observed range, not a confidence interval. No positive saving is assumed.</p><div id="ab" class="chart"></div></section><section class="card"><h2>Search energy · R vs S</h2><div id="search" class="chart"></div></section><section class="card"><h2>Latency against its SLO</h2><div id="latency" class="chart"></div></section><section class="card"><h2>Dev quality against its threshold</h2><p class="muted">A passing count is within the declared tolerance on this evaluation; it is not statistical equivalence.</p><div id="quality" class="chart"></div></section><section class="card"><h2>GPU joules per completed request</h2><div id="requestEnergy" class="chart"></div></section></div>
<section class="card"><h2>Fresh confirmation · headline evidence</h2><div id="headline"></div><div id="paired"></div></section>
<section class="card"><h2>Recorded power replay</h2><select id="selected" aria-label="Recorded trial"></select><p class="muted">Actual NVML samples, downsampled for display only. Original trial artifacts preserve the full readings. Averaged power polls are not independent samples.</p><div id="power" class="chart"></div><div id="detail" class="event"></div></section>
<section class="card"><h2>Every attempt</h2><div id="trials" class="table-wrap"></div></section><section class="card"><h2>Hypotheses and accept / revert decisions</h2><div id="timeline" class="timeline"></div></section>
</main><footer>GPU energy (NVML) · fixed hardware and workload scope · failures and null results retained · standalone offline artifact</footer>
<script id="study-data" type="application/json">__STUDY_DATA__</script>
<script>
'use strict';
const DATA=JSON.parse(document.getElementById('study-data').textContent),NS='http://www.w3.org/2000/svg';let active=[],timer=null;
const $=id=>document.getElementById(id), n=v=>typeof v==='number'&&Number.isFinite(v), fmt=v=>n(v)?Number(v.toPrecision(5)).toString():'—';
function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function svgEl(tag,attrs,text){const e=document.createElementNS(NS,tag);Object.entries(attrs||{}).forEach(([k,v])=>e.setAttribute(k,v));if(text!==undefined)e.textContent=text;return e}
function color(r){return r.arm==='R'?'#1c8c72':r.arm==='S'?'#3567bb':r.phase==='confirmation'?'#865ac4':r.dtype==='fp8'?'#d29128':'#58758c'}
function frontier(rows){return rows.filter(r=>r.eligible&&!rows.some(q=>q.eligible&&q!==r&&q.p95_latency_s<=r.p95_latency_s&&q.joules_per_output_token<=r.joules_per_output_token&&(q.p95_latency_s<r.p95_latency_s||q.joules_per_output_token<r.joules_per_output_token))).sort((a,b)=>a.p95_latency_s-b.p95_latency_s)}
function chart(target,rows,xkey,ykey,xlabel,ylabel,options={}){target.replaceChildren();const W=680,H=350,L=72,R=20,T=25,B=65,points=rows.filter(r=>n(r[xkey])&&n(r[ykey])),sv=svgEl('svg',{viewBox:`0 0 ${W} ${H}`,role:'img'});target.append(sv);let xmax=Math.max(1,...points.map(r=>r[xkey]),options.vline||0)*1.08,ymax=Math.max(1,...points.map(r=>r[ykey]),options.hline||0)*1.12;const X=v=>L+v/xmax*(W-L-R),Y=v=>H-B-v/ymax*(H-T-B);
for(let i=0;i<=5;i++){let xx=L+(W-L-R)*i/5,yy=T+(H-T-B)*i/5;sv.append(svgEl('path',{d:`M${xx} ${T}V${H-B}M${L} ${yy}H${W-R}`,stroke:'#e6edf2',fill:'none'}),svgEl('text',{x:xx,y:H-B+22,'text-anchor':'middle','font-size':11,fill:'#647a8a'},options.xlabels?options.xlabels[i]:fmt(xmax*i/5)),svgEl('text',{x:L-10,y:yy+4,'text-anchor':'end','font-size':11,fill:'#647a8a'},fmt(ymax*(5-i)/5)))}
if(n(options.vline))sv.append(svgEl('path',{d:`M${X(options.vline)} ${T}V${H-B}`,stroke:'#c13c45','stroke-dasharray':'5 4'}));if(n(options.hline)){sv.append(svgEl('path',{d:`M${L} ${Y(options.hline)}H${W-R}`,stroke:'#c13c45','stroke-dasharray':'5 4'}),svgEl('text',{x:L+5,y:Y(options.hline)-7,'font-size':11,fill:'#a2363d'},options.lineLabel||'Declared threshold'))}
if(options.frontier){const fr=frontier(points);if(fr.length>1)sv.append(svgEl('polyline',{points:fr.map(r=>`${X(r[xkey])},${Y(r[ykey])}`).join(' '),stroke:'#9babb8',fill:'none','stroke-dasharray':'5 4'}))}
if(options.lines){const groups=new Map;points.forEach(r=>{let k=r.arm||r.config_label||'trace';if(!groups.has(k))groups.set(k,[]);groups.get(k).push(r)});groups.forEach(rs=>sv.append(svgEl('polyline',{points:rs.map(r=>`${X(r[xkey])},${Y(r[ykey])}`).join(' '),stroke:color(rs[0]),fill:'none','stroke-width':1.5,opacity:.6})))}
points.forEach(r=>{const c=svgEl('circle',{cx:X(r[xkey]),cy:Y(r[ykey]),r:4.6,fill:color(r),opacity:r.eligible===false?.42:.85});c.append(svgEl('title',{},`${r.id||''} · ${r.config_label||r.dtype||''}\n${xlabel}: ${fmt(r[xkey])}\n${ylabel}: ${fmt(r[ykey])}`));if(r.id)c.addEventListener('click',()=>selectTrial(r.id));sv.append(c)});
if(!points.length)sv.append(svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#718797','font-size':14},'No recorded observations'));sv.append(svgEl('text',{x:(L+W-R)/2,y:H-12,'text-anchor':'middle','font-size':12,fill:'#3c5d72'},xlabel),svgEl('text',{transform:`translate(15 ${(T+H-B)/2}) rotate(-90)`,'text-anchor':'middle','font-size':12,fill:'#3c5d72'},ylabel));return {sv,X,Y,points}}
function table(target,rows){target.replaceChildren();const t=element('table'),head=element('thead'),hr=element('tr'),cols=[['id','Trial'],['phase','Phase'],['arm','Arm'],['load_label','Load'],['config_label','Config'],['mode','Evidence'],['status','Status'],['eligible','Eligible'],['joules_per_output_token','J/token'],['joules_per_completed_request','J/request'],['p95_latency_s','p95 latency'],['quality_correct','Quality correct'],['length_drift_flagged','Length drift'],['decision_reason','Decision']];cols.forEach(c=>hr.append(element('th',c[1])));head.append(hr);t.append(head);const body=element('tbody');rows.forEach(r=>{const tr=element('tr');cols.forEach(([key])=>tr.append(element('td',n(r[key])?fmt(r[key]):r[key]===null||r[key]===undefined?'—':String(r[key]))));tr.addEventListener('click',()=>selectTrial(r.id));body.append(tr)});t.append(body);target.append(t);if(!rows.length)target.append(element('p','No eligible records.','muted'))}
function dropdown(id,values){const sel=$(id);sel.replaceChildren();['all',...values].forEach(v=>{const op=element('option',v);op.value=v;sel.append(op)});sel.addEventListener('change',render)}
function selectTrial(id){$('selected').value=id;detail()}
function detail(){const r=active.find(r=>r.id===$('selected').value);if(!r){$('detail').textContent='No trial selected';return}const powers=(r.power_samples||[]).map(p=>({t:p.t,w:p.w,config_label:'power'}));chart($('power'),powers,'t','w','Seconds from first recorded sample','GPU power (W)',{lines:true});$('detail').replaceChildren(element('strong',`${r.id} · ${r.status} · ${r.mode}`),element('div',r.hypothesis||'No model hypothesis recorded.'),element('div',r.decision_reason||'No accept/revert decision recorded.','reason'),element('div',`Quality ${r.quality_correct??'—'} / ${r.quality_items??'—'}; allocated ${fmt(r.allocated_seconds)} seconds; length drift ${r.length_drift_flagged??'not recorded'}.`,'muted'))}
function render(){active=DATA.rows.filter(r=>($('phase').value==='all'||r.phase===$('phase').value)&&($('load').value==='all'||String(r.load_label||'unspecified')===$('load').value)&&($('arm').value==='all'||String(r.arm||'none')===$('arm').value)&&($('mode').value==='all'||r.mode===$('mode').value));const observations=active.filter(r=>r.live_observation||($('mode').value==='synthetic_fixture'&&r.mode==='synthetic_fixture')),search=observations.filter(r=>r.phase==='search').map((r,i)=>({...r,order:i+1}));$('maps').replaceChildren();[...new Set(observations.filter(r=>r.phase==='map').map(r=>String(r.load_label||'unspecified')))].forEach(load=>{const box=element('div'),title=element('h3',load+($('mode').value==='synthetic_fixture'?' · SYNTHETIC FIXTURE':'')),plot=element('div',undefined,'chart');box.append(title,plot);$('maps').append(box);chart(plot,observations.filter(r=>r.phase==='map'&&String(r.load_label||'unspecified')===load),'p95_latency_s','joules_per_output_token','p95 latency (s)','GPU J/output token',{frontier:true,vline:DATA.slo})});if(!$('maps').children.length)$('maps').append(element('p','No recorded map observations in this selection.','muted'));
const loads=[...new Set(observations.filter(r=>r.phase==='map').map(r=>String(r.load_label||'unspecified')))],overview=observations.filter(r=>r.phase==='map').map(r=>({...r,load_index:loads.indexOf(String(r.load_label||'unspecified'))+1}));chart($('overview'),overview,'load_index','joules_per_output_token','Recorded load index (see map labels)','GPU J/output token',{lines:true});const ab=observations.filter(r=>r.phase==='ab').map(r=>({...r,dtype_index:r.dtype==='bf16'?1:2})),abchart=chart($('ab'),ab,'dtype_index','joules_per_output_token','1 = BF16 · 2 = FP8','GPU J/output token');[1,2].forEach(group=>{const rs=ab.filter(r=>r.dtype_index===group&&n(r.joules_per_output_token));if(!rs.length)return;const ys=rs.map(r=>r.joules_per_output_token).sort((a,b)=>a-b),mid=ys.length%2?ys[(ys.length-1)/2]:(ys[ys.length/2-1]+ys[ys.length/2])/2,x=abchart.X(group);abchart.sv.append(svgEl('path',{d:`M${x} ${abchart.Y(ys[0])}V${abchart.Y(ys[ys.length-1])}M${x-12} ${abchart.Y(mid)}H${x+12}`,stroke:'#152b3e','stroke-width':2}))});chart($('search'),search,'order','joules_per_output_token','Recorded search order','GPU J/output token',{lines:true});chart($('latency'),search,'order','p95_latency_s','Recorded search order','p95 latency (s)',{lines:true,hline:DATA.slo,lineLabel:'Latency SLO'});chart($('quality'),search,'order','quality_correct','Recorded search order','Correct dev answers',{lines:true,hline:DATA.quality_threshold,lineLabel:`Quality threshold ${DATA.quality_threshold??''}`});chart($('requestEnergy'),search,'order','joules_per_completed_request','Recorded search order','GPU J/completed request',{lines:true});table($('trials'),active);const sel=$('selected'),old=sel.value;sel.replaceChildren();active.forEach(r=>{const op=element('option',r.id);op.value=r.id;sel.append(op)});if(active.some(r=>r.id===old))sel.value=old;detail();$('timeline').replaceChildren();active.forEach(r=>{const e=element('div',undefined,'event');e.style.borderLeftColor=color(r);e.append(element('strong',`${r.id} · ${r.arm||r.phase} · ${r.accepted===true?'accepted':r.accepted===false?'reverted / rejected':'decision unrecorded'}`),element('div',r.hypothesis||'No hypothesis recorded.'),element('div',r.decision_reason||'No decision reason recorded.','reason'));$('timeline').append(e)})}
function renderTimeline(){if(!DATA.timeline.length)return;const entries=DATA.timeline.filter(r=>($('phase').value==='all'||$('phase').value==='search')&&($('arm').value==='all'||r.arm===$('arm').value)&&($('load').value==='all'||String(r.load_label||'unspecified')===$('load').value)&&($('mode').value==='all'||r.mode===$('mode').value));$('timeline').replaceChildren();entries.forEach(r=>{const e=element('div',undefined,'event');e.style.borderLeftColor=color(r);e.append(element('strong',`${r.id} · ${r.arm} · ${r.accepted===true?'accepted':r.accepted===false?'reverted / rejected':'decision unrecorded'}`),element('div',r.hypothesis||'No hypothesis recorded.'),element('div',r.decision_reason||'No reason recorded.','reason'),element('div',`Allocated ${fmt(r.allocated_seconds)} seconds, planner wait ${fmt(r.planner_wait_seconds)} seconds; length drift ${r.length_drift_flagged??'not recorded'}.`,'muted'));$('timeline').append(e)})}
dropdown('phase',[...new Set(DATA.rows.map(r=>r.phase))]);dropdown('load',[...new Set(DATA.rows.map(r=>String(r.load_label||'unspecified')))]);dropdown('arm',[...new Set(DATA.rows.map(r=>String(r.arm||'none')))]);dropdown('mode',[...new Set(DATA.rows.map(r=>r.mode))]);if(DATA.rows.some(r=>r.mode==='live'))$('mode').value='live';else if(DATA.synthetic_only)$('mode').value='synthetic_fixture';$('selected').addEventListener('change',detail);['phase','load','arm','mode'].forEach(id=>$(id).addEventListener('change',renderTimeline));
const notices=[...DATA.warnings];if(!DATA.sealed)notices.push('Unsealed checkpoint: headline results are withheld.');if(DATA.synthetic_only)notices.push('SYNTHETIC FIXTURES ONLY: charts exercise software replay. No GPU energy measurement, savings or model-quality conclusion is established.');if(notices.length)$('notice').append(element('p',notices.join(' '),'warn'));[['Study',DATA.status],['Verified live trials',DATA.rows.filter(r=>r.live_observation).length],['Fresh headline observations',DATA.headline.length],['Conditional floor',DATA.floor.established?'supported':'not established']].forEach(([label,value])=>{const s=element('div',undefined,'stat');s.append(element('div',String(value),'big'),element('div',label,'muted'));$('stats').append(s)});table($('headline'),DATA.headline);if(DATA.quality_note)$('paired').append(element('p',DATA.quality_note,'muted'));DATA.paired_quality.forEach(r=>$('paired').append(element('p',`${r.config_label}: ${r.candidate_correct}/300 vs ${r.reference_correct}/300 reference; ${r.paired_lost} lost, ${r.paired_gained} gained; within 2 pp tolerance: ${r.passed}.`,'muted')));
$('play').addEventListener('click',()=>{if(timer){clearInterval(timer);timer=null;$('play').textContent='Replay trials';return}let i=0;$('play').textContent='Pause replay';timer=setInterval(()=>{if(!active.length||i>=active.length){clearInterval(timer);timer=null;$('play').textContent='Replay trials';return}selectTrial(active[i++].id)},1000)});render();renderTimeline();
</script></html>'''
