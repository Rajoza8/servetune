"""Reuse one sealed, complete bf16 development reference without rescoring.

Performance repeats are deliberately not imported. This is a continuation of
the same frozen reference, not a new model sample or a choice of a better score.
"""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil

from .artifacts import digest, file_hash, timestamp, verify, write_json
from .config import validate
from .engine import engine_command
from .quality import SCORER_POLICY, evaluate_gate, normalize_answer, scorer_sha256


def _load(path):
    return json.loads(Path(path).read_text())


def _semantic_config(config):
    result = deepcopy(validate(config))
    # Files may be moved between hosts; identity is established separately by
    # the complete frozen manifest and every corresponding file checksum.
    result["data"] = {key: None for key in result["data"]}
    return result


def _validate_config_transition(saved_config, current_config):
    saved = _semantic_config(saved_config)
    current = _semantic_config(current_config)
    previous_window = saved["trace"]["duration_s"]
    current_window = current["trace"]["duration_s"]
    if current_window < previous_window:
        raise ValueError("A saved quality reference cannot authorize a shorter performance-calibration window")
    # The quality request sequence does not depend on performance-trace
    # duration. V4 explicitly lengthens that window when noise is too high;
    # this single calibration change must not reset a once-measured reference.
    current["trace"]["duration_s"] = previous_window
    if current != saved:
        raise ValueError("Reference protocol differs outside an increased trace.duration_s")
    return {
        "source_trace_duration_s": previous_window,
        "current_trace_duration_s": current_window,
        "increased": current_window > previous_window,
        "allowed_change": "trace.duration_s increase only; all other protocol fields unchanged",
        "reason": "P4 performance-window calibration may be lengthened; the once-measured bf16 quality reference and its request protocol remain unchanged",
    }


def _semantic_manifest(manifest):
    result = deepcopy(manifest)
    if not isinstance(result, dict) or not isinstance(result.get("files"), dict):
        raise ValueError("Missing frozen data-file identities")
    if set(result["files"]) != {"prompts", "dev", "final", "provenance"}:
        raise ValueError("Incomplete frozen data-file identities")
    for row in result["files"].values():
        if not isinstance(row, dict) or not isinstance(row.get("sha256"), str):
            raise ValueError("Invalid frozen data checksum")
        row.pop("path", None)
    return result


def _function_ast(path, name):
    tree = ast.parse(Path(path).read_text())
    matches = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == name]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous frozen quality-evaluation function")
    return ast.dump(matches[0], include_attributes=False)


def _engine_ast_except_port_probe(path):
    tree = ast.parse(Path(path).read_text())
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ManagedEngine"]
    if len(classes) != 1:
        raise ValueError("Missing or ambiguous frozen ManagedEngine implementation")
    methods = [node for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name == "_port_free"]
    if len(methods) != 1:
        raise ValueError("Missing or ambiguous engine port-availability probe")
    classes[0].body.remove(methods[0])
    return ast.dump(tree, include_attributes=False)


def _validate_saved_score(baseline, dev_items):
    if len(dev_items) != 150:
        raise ValueError("A frozen development reference must contain 150 items")
    if (baseline.get("items_sha256") != digest(dev_items)
            or baseline.get("item_ids") != [row["id"] for row in dev_items]
            or baseline.get("scorer_sha256") != scorer_sha256()
            or baseline.get("policy") != SCORER_POLICY):
        raise ValueError("Saved reference items, scorer, or policy differ from the current frozen protocol")
    # The existing gate checks exact sizes, unique paired rows, numeric counts,
    # and aggregate/row consistency. Comparing a reference to itself is only a
    # structural check; no candidate quality or new model result is inferred.
    evaluate_gate(baseline, baseline, "dev")
    if baseline["failed_requests"] != 0:
        raise ValueError("Cannot import a reference with failed evaluation requests")
    rows = baseline["results"]
    if (baseline.get("incorrect") != 150 - baseline["correct"]
            or baseline.get("score") != baseline["correct"] / 150
            or type(baseline.get("truncated_answers")) is not int):
        raise ValueError("Saved reference aggregate counts are inconsistent")
    for item, row in zip(dev_items, rows):
        if (item["id"] != row["id"] or type(row.get("truncated")) is not bool
                or row["failed_request"] is not False):
            raise ValueError("Saved reference rows have changed order or invalid outcomes")
        extracted = row.get("extracted_answer")
        if extracted is not None and not isinstance(extracted, str):
            raise ValueError("Saved extracted answers must be text or null")
        try:
            correct = extracted is not None and normalize_answer(extracted) == normalize_answer(item["answer"])
        except ValueError:
            correct = False
        if row["correct"] is not bool(correct):
            raise ValueError("Saved per-item correctness disagrees with the frozen answer/scorer")
    if baseline["truncated_answers"] != sum(row["truncated"] for row in rows):
        raise ValueError("Saved truncation count disagrees with per-item outcomes")


def import_dev_baseline(source_dir, destination, *, config, hardware, dev_items, data_evidence):
    """Validate and copy a directly measured reference from a sealed live run.

    A later failure in that run is allowed. Its original reference must have
    completed, with zero failed requests and complete default-bf16 identity.
    Only the isolated port-availability probe may differ in engine source.
    Performance-trace duration may increase for P4 calibration; every other
    trace, measurement, quality, and engine setting must remain unchanged.
    No GPU, model, paid provider, or final-evaluation calls occur here.
    """
    source = Path(source_dir)
    destination = Path(destination)
    if source.is_symlink() or (source / "manifest.json").is_symlink():
        raise ValueError("Baseline source must not be a symlink")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Imported baseline destination already exists")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Baseline source contains a symlink")
    report = verify(source)
    source_manifest_hash = file_hash(source / "manifest.json")
    quality_gate = report.get("checks", {}).get("quality_baseline", {})
    if (report.get("mode") != "live" or quality_gate.get("status") != "pass"
            or quality_gate.get("evidence") != "dev-baseline.json"
            or quality_gate.get("imported")):
        raise ValueError("Import requires a directly measured, complete live development reference")
    saved_config = _load(source / "config.json")
    if report.get("config_sha256") != digest(saved_config):
        raise ValueError("Saved config hash disagrees with its sealed report")
    performance_window = _validate_config_transition(saved_config, config)
    if saved_config["engine"]["use_engine_defaults"] is not True:
        raise ValueError("Reference must use the engine-default bf16 configuration")
    if _load(source / "quality_gate.json") != config["quality"]:
        raise ValueError("Frozen quality-gate artifact differs")
    saved_data = _load(source / "data-manifest.json")
    if _semantic_manifest(saved_data) != _semantic_manifest(data_evidence):
        raise ValueError("Reference data manifest, split, scorer, or file hashes differ")
    saved_hardware = _load(source / "hardware.json")
    if saved_hardware.get("status") != "pass" or hardware.get("status") != "pass":
        raise ValueError("Both reference and current hardware probes must pass")
    for field in ("uuid", "name", "total_memory_mib", "compute_capability"):
        if saved_hardware.get("gpu", {}).get(field) != hardware.get("gpu", {}).get(field):
            raise ValueError("Reference physical GPU identity differs")
    for field in ("driver_version", "vllm_version"):
        if not hardware.get(field) or saved_hardware.get(field) != hardware[field]:
            raise ValueError("Reference driver or vLLM version differs")
    metadata = _load(source / "bf16-1" / "engine-metadata.json")
    expected_command = engine_command({**config["engine"], "gpu_uuid": hardware["gpu"]["uuid"]}, "bf16")
    expected_identity = {
        "dtype": "bf16", "model_id": config["engine"]["model_id"],
        "model_revision": config["engine"]["model_revision"],
        "tokenizer_revision": config["engine"].get("tokenizer_revision") or config["engine"]["model_revision"],
        "gpu_uuid": hardware["gpu"]["uuid"], "vllm_version": hardware["vllm_version"],
        "baseline_policy": "engine_defaults_under_fixed_context_and_cache_policy",
        "identity_complete": True, "cleanup_status": "completed", "argv": expected_command,
    }
    if any(metadata.get(key) != value for key, value in expected_identity.items()):
        raise ValueError("Reference bf16 engine command, revision, identity, or cleanup differs")
    current_source = Path(__file__).parent
    for name in ("quality.py", "workload.py"):
        if file_hash(source / "source" / name) != file_hash(current_source / name):
            raise ValueError(f"Reference {name} implementation differs")
    if (_function_ast(source / "source" / "preflight.py", "_quality_baseline")
            != _function_ast(current_source / "preflight.py", "_quality_baseline")):
        raise ValueError("Reference quality request/prompt implementation differs")
    if (_engine_ast_except_port_probe(source / "source" / "engine.py")
            != _engine_ast_except_port_probe(current_source / "engine.py")):
        raise ValueError("Engine source changed outside ManagedEngine._port_free")
    baseline = _load(source / "dev-baseline.json")
    _validate_saved_score(baseline, dev_items)
    # Preserve the complete sealed original, not only a floating score. A fresh
    # verification of the copied tree also catches concurrent source mutation.
    destination.mkdir(parents=True, exist_ok=False)
    copied = destination / "source-run"
    shutil.copytree(source, copied, symlinks=False)
    verify(copied)
    if file_hash(copied / "manifest.json") != source_manifest_hash:
        raise ValueError("Baseline source changed during evidence import")
    copied_baseline = _load(copied / "dev-baseline.json")
    if copied_baseline != baseline:
        raise ValueError("Baseline source changed during evidence import")
    origin = {
        "schema_version": 1, "imported_at": timestamp(), "source_directory": str(source.resolve()),
        "source_manifest_sha256": source_manifest_hash,
        "source_preflight_sha256": file_hash(copied / "preflight.json"),
        "source_baseline_sha256": file_hash(copied / "dev-baseline.json"),
        "original_preflight_status": report.get("status"), "gpu_uuid": hardware["gpu"]["uuid"],
        "model_revision": config["engine"]["model_revision"],
        "correct": baseline["correct"], "items": 150, "failed_requests": 0,
        "scorer_sha256": baseline["scorer_sha256"],
        "source_engine_sha256": file_hash(copied / "source" / "engine.py"),
        "current_engine_sha256": file_hash(current_source / "engine.py"),
        "allowed_engine_change_scope": "ManagedEngine._port_free only (AST checked)",
        "performance_window": performance_window,
        "claim": "Same once-measured frozen bf16 reference; no new quality sample, no score selection, no imported performance repeats",
    }
    write_json(destination / "origin.json", origin)
    return {"baseline": baseline, "origin": origin,
            "baseline_bytes": (copied / "dev-baseline.json").read_bytes()}
