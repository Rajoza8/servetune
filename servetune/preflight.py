"""Run P1/P1b/P2/P3/P4 without treating local fixtures as GPU evidence."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import statistics
import time

from .artifacts import canonical, digest, file_hash, seal, timestamp, write_json
from .config import validate
from .deadline import SessionDeadline, TimeBudgetExceeded
from .engine import ManagedEngine
from .hardware import probe_hardware
from .power import PowerMeter, PowerError
from .quality import score_items, validate_dataset_manifest
from .workload import coefficient_of_variation, completion, make_trace, run_trace


def _gate(status, reason, **evidence):
    return {"status": status, "reason": reason, **evidence}


def render_report(result):
    rows = ["# ServeTune preflight", "", f"Mode: **{result['mode']}**. Status: **{result['status']}**.",
            "", "Synthetic runs are software checks and cannot pass a live GPU gate.", "",
            "| Check | Status | Evidence / reason |", "| --- | --- | --- |"]
    for name, gate in result["checks"].items():
        reason = gate.get("reason", "Check completed").replace("|", "/").replace("\n", " ")
        rows.append(f"| {name} | {gate['status']} | {reason} |")
    rows += ["", f"Live preflight passed: **{result['live_preflight_passed']}**.",
             f"Measurement prerequisites passed: **{result['measurement_prerequisites_passed']}**.",
             "", "The energy-map floor has not been built by preflight. This command records its prerequisites.",
             "", "Quality wording: **within the predeclared 2-percentage-point tolerance**.",
             "Arm budgets count allocated wall-clock intervals only; the other arm's intervals are paused.",
             "", "Energy label: GPU energy (NVML). Full trace energy includes queue draining.",
             "Final evaluation contents are hashed and checked for split integrity, never sent to the model here.",
             "", "See preflight.json, events.jsonl, source/, and manifest.json for structured evidence."]
    return "\n".join(rows) + "\n"


def _snapshot_source(root):
    destination = root / "source"
    destination.mkdir()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        (destination / path.name).write_bytes(path.read_bytes())


def _load_data(config):
    data = config["data"]
    if any(data[name] is None for name in ("prompts", "dev", "final", "provenance")):
        raise ValueError("Prepare public prompts and disjoint 150/300 quality sets with prepare-data, then pass --data-dir")
    prompts, dev, final, provenance = [json.loads(Path(data[name]).read_text())
                                       for name in ("prompts", "dev", "final", "provenance")]
    split_check = validate_dataset_manifest(dev, final)
    # Performance prompts must not leak either quality split into the tuning workload.
    if not isinstance(prompts, list) or not prompts or any(type(p) is not str or not p.strip() for p in prompts):
        raise ValueError("Invalid public workload prompts")
    quality_prompts = {row.get("prompt", row.get("question")) for row in dev + final}
    if any(prompt in quality_prompts for prompt in prompts):
        raise ValueError("Performance prompts overlap the quality evaluations")
    if provenance.get("origin") == "synthetic_fixture" or not provenance.get("license"):
        raise ValueError("Live preflight needs recorded public data and license provenance")
    hashes = provenance.get("files_sha256", {})
    for name in ("prompts", "dev", "final"):
        if hashes.get(f"{name}.json") != file_hash(data[name]):
            raise ValueError(f"Frozen {name} data no longer matches the recorded source selection")
    if provenance.get("quality_manifest") != split_check:
        raise ValueError("Frozen quality manifest/scorer no longer matches its provenance")
    return prompts, dev, {"split_validation": split_check,
                          "files": {name: {"path": data[name], "sha256": file_hash(data[name])} for name in data},
                          "provenance": provenance}


def _calibration(energy):
    if energy["method"] != "nvml_total_energy_counter":
        return {"pass": False, "reason": "Power integration retained as diagnostics; cumulative-counter gate not met"}
    samples = energy["samples"]
    increments = [b["energy_mj"] - a["energy_mj"] for a, b in zip(samples, samples[1:])
                  if b["energy_mj"] > a["energy_mj"]]
    if len(increments) < 2:
        return {"pass": False, "reason": "Insufficient counter updates to bound boundary granularity"}
    # Conservative polling-scale bound for two uncertain window boundaries. This
    # is not a sensor calibration or a claim about absolute NVML accuracy.
    relative_bound = 2 * max(increments) / 1000 / energy["joules"]
    return {"pass": relative_bound < 0.01, "observed_boundary_relative_bound": relative_bound,
            "reason": "Two maximum observed update steps / workload energy; require <1%",
            "update_intervals_s": energy.get("observed_update_intervals_s", [])}


def _quality_baseline(engine, items, config, deadline=None):
    deadline = deadline or SessionDeadline()
    outputs = []
    for item in items:
        try:
            prompt = item.get("prompt", item.get("question")) + "\n\nPut your final numeric answer on its own line as #### <answer>."
            answer = completion(engine.base_url, prompt,
                                config["quality"]["max_output_tokens"], deadline.timeout(config["engine"]["request_timeout_s"]))
            outputs.append({"id": item["id"], "text": answer["text"],
                            "finish_reason": answer["finish_reason"], "error": None})
        except TimeBudgetExceeded:
            write_json(engine.artifact_dir / "dev-baseline-partial.json", {"status": "incomplete", "outputs": outputs})
            raise
        except Exception as exc:
            outputs.append({"id": item["id"], "text": "", "error": type(exc).__name__})
    return score_items(items, outputs)


def run_preflight(config, output, *, simulate=False, with_spark=False, ledger_path=None,
                  max_runtime_s=None, spark_evidence=None, dev_baseline_evidence=None):
    """Fresh output directories only. Live serving is never invoked in simulate mode."""
    validate(config)
    if with_spark and spark_evidence is not None:
        raise ValueError("Use either --with-spark or --spark-evidence, never both")
    if simulate and spark_evidence is not None:
        raise ValueError("Simulation cannot import real paid P3 evidence")
    if simulate and dev_baseline_evidence is not None:
        raise ValueError("Simulation cannot import a live development reference")
    deadline = SessionDeadline(max_runtime_s)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    _snapshot_source(root)
    write_json(root / "config.json", config)
    write_json(root / "quality_gate.json", config["quality"])
    result = {"schema_version": 1, "created_at": timestamp(),
              "mode": "synthetic_fixture" if simulate else "live",
              "config_sha256": digest(config), "checks": {name: _gate("skipped", "Not reached")
                  for name in ("P1", "P1b", "P2", "P3", "P4", "quality_baseline")},
              "status": "blocked", "live_preflight_passed": False,
              "measurement_prerequisites_passed": False, "floor_built": False,
              "budget_caps_usd": {"meta": 15, "baseten": 5}, "paid_calls_this_run": 0}
    result["session_budget_seconds"] = max_runtime_s
    events = (root / "events.jsonl").open("x", buffering=1)

    def event(name, **details):
        row = {"at": timestamp(), "event": name, **details}
        events.write(canonical(row).decode() + "\n")
        print(json.dumps(row, allow_nan=False), flush=True)

    try:
        event("preflight_started", mode=result["mode"])
        if simulate:
            _simulate(config, root, result, event)
        else:
            _live(config, root, result, event, deadline,
                  dev_baseline_evidence=dev_baseline_evidence)
            result["measurement_prerequisites_passed"] = all(result["checks"][x]["status"] == "pass"
                                                              for x in ("P1", "P2", "P4"))
            if spark_evidence is not None:
                from .planner import import_spark_evidence
                if ledger_path is None:
                    raise ValueError("Importing P3 evidence requires the cumulative ServeTune ledger")
                try:
                    result["checks"]["P3"] = import_spark_evidence(
                        Path(ledger_path), Path(spark_evidence), root / "spark-imported")
                    result["paid_calls_this_run"] = 0
                    event("saved_spark_evidence_imported", paid_calls_this_run=0,
                          reservation_id=result["checks"]["P3"]["reservation_id"])
                except (ValueError, OSError) as exc:
                    result["checks"]["P3"] = _gate("fail", "Saved P3 evidence failed ledger/hash/protocol validation",
                                                  error_type=type(exc).__name__)
                    event("saved_spark_evidence_rejected", error_type=type(exc).__name__)
            elif (with_spark and result["measurement_prerequisites_passed"]
                    and result["checks"]["quality_baseline"]["status"] == "pass"):
                from .planner import run_spark_check
                if ledger_path is None:
                    raise ValueError("P3 requires the cumulative ServeTune ledger")
                deadline.require(60)
                result["checks"]["P3"] = run_spark_check(Path(ledger_path), root / "spark")
                # Read actual call evidence, rather than treating a missing key as a paid call.
                result["paid_calls_this_run"] = result["checks"]["P3"].get("paid_calls", 0)
            elif not with_spark:
                result["checks"]["P3"] = _gate("skipped", "Use --spark-evidence to reuse a verified check or --with-spark for one bounded paid check")
            result["live_preflight_passed"] = (result["measurement_prerequisites_passed"]
                and result["checks"]["P3"]["status"] == "pass"
                and result["checks"]["quality_baseline"]["status"] == "pass")
            required = ("P1", "P2", "P3", "P4", "quality_baseline")
            result["status"] = ("pass" if result["live_preflight_passed"] else
                                "fail" if any(result["checks"][x]["status"] == "fail" for x in required) else "blocked")
    except TimeBudgetExceeded:
        result["status"] = "incomplete"
        result["stop_reason"] = "Allocated session time exhausted; no new work started and owned engine cleanup requested"
        event("session_time_limit_reached")
    except Exception as exc:
        # Errors remain evidence. Do not swallow KeyboardInterrupt/SystemExit.
        result["status"] = "fail"
        result["error"] = {"type": type(exc).__name__, "message": "Preflight interrupted by an internal/operational error; inspect recorded phase evidence"}
        event("preflight_error", error_type=type(exc).__name__)
    finally:
        result["finished_at"] = timestamp()
        event("preflight_finished", status=result["status"])
        events.close()
        write_json(root / "preflight.json", result)
        (root / "preflight.md").write_text(render_report(result))
        seal(root)
    return result


def _live(config, root, result, event, deadline=None, *, dev_baseline_evidence=None):
    deadline = deadline or SessionDeadline()
    checks = result["checks"]
    hardware = probe_hardware(config["engine"]["gpu_index"])
    write_json(root / "hardware.json", hardware)
    event("hardware_probed", status=hardware["status"])
    if hardware["status"] != "pass":
        checks["P1"] = _gate("blocked", "; ".join(hardware["blockers"]), evidence="hardware.json")
        return
    if config["engine"]["model_revision"] is None:
        checks["P1"] = _gate("blocked", "Pin --model-revision to the exact 40-character Hub commit before loading weights")
        return
    try:
        prompts, dev, data_evidence = _load_data(config)
    except (ValueError, OSError, KeyError) as exc:
        checks["P1"] = _gate("blocked", str(exc))
        return
    write_json(root / "data-manifest.json", data_evidence)
    if not config["engine"]["use_engine_defaults"]:
        checks["P1"] = _gate("blocked", "The frozen preflight reference must use engine defaults under the fixed context/cache policy")
        return
    engine_config = {**config["engine"], "gpu_uuid": hardware["gpu"]["uuid"]}
    gpu_uuid = hardware["gpu"]["uuid"]
    saved_baseline = None
    if dev_baseline_evidence is not None:
        from .evidence import import_dev_baseline
        try:
            imported = import_dev_baseline(dev_baseline_evidence, root / "dev-baseline-imported",
                config=config, hardware=hardware, dev_items=dev, data_evidence=data_evidence)
            saved_baseline = imported["baseline"]
            with (root / "dev-baseline.json").open("xb") as stream:
                stream.write(imported["baseline_bytes"])
            checks["quality_baseline"] = _gate("pass",
                "Same once-measured frozen bf16 default reference; no new quality sample; final eval untouched",
                evidence="dev-baseline.json", imported=True,
                correct=saved_baseline["correct"], items=saved_baseline["items"],
                origin="dev-baseline-imported/origin.json")
            event("saved_dev_baseline_imported", correct=saved_baseline["correct"], items=150,
                  source_manifest_sha256=imported["origin"]["source_manifest_sha256"])
        except (ValueError, OSError, KeyError, TypeError, SyntaxError) as exc:
            checks["quality_baseline"] = _gate("fail",
                "Saved development reference failed seal/identity/protocol/count validation; no replacement score was measured",
                error_type=type(exc).__name__)
            event("saved_dev_baseline_rejected", error_type=type(exc).__name__)
            return
    trace = make_trace(prompts, config["trace"])
    write_json(root / "trace.json", trace)
    settings = config["measurement"]
    try:
        deadline.require(settings["idle_seconds"] + 1)
        idle_meter = PowerMeter(config["engine"]["gpu_index"], settings["allow_power_fallback"], gpu_uuid=gpu_uuid)
        idle_meter.start()
        time.sleep(settings["idle_seconds"])
        idle = idle_meter.stop()
        write_json(root / "idle-energy.json", idle)
    except TimeBudgetExceeded:
        raise
    except Exception as exc:
        checks["P2"] = _gate("blocked", f"Energy telemetry unavailable: {type(exc).__name__}")
        return
    if idle["method"] != "nvml_total_energy_counter":
        checks["P2"] = _gate("fail", "Averaged-power fallback recorded; current v4 objective requires a usable cumulative counter")
        return
    runs, calibrations = [], []
    for repeat in range(settings["repeats"]):
        # Refuse a new repeat unless its trace plus bounded request-drain time
        # fits. Startup and each request are independently capped below.
        deadline.require(config["trace"]["duration_s"] + config["engine"]["request_timeout_s"] + 1)
        directory = root / f"bf16-{repeat + 1}"
        bounded_config = {**engine_config, "startup_timeout_s": deadline.timeout(engine_config["startup_timeout_s"])}
        engine = ManagedEngine(bounded_config, directory, "bf16")
        phase = "serving"
        try:
            event("engine_starting", dtype="bf16", repeat=repeat + 1)
            with engine:
                smoke = completion(engine.base_url, "Reply with the single word ready.", 2048,
                                   deadline.timeout(config["engine"]["request_timeout_s"]), temperature=1)
                write_json(directory / "smoke.json", smoke)
                if not smoke["text"].strip() or smoke["finish_reason"] != "stop":
                    raise ValueError("Smoke completion did not finish with a nonempty final answer")
                for _ in range(settings["warmup_requests"]):
                    completion(engine.base_url, prompts[0], config["trace"]["max_output_tokens"],
                               deadline.timeout(config["engine"]["request_timeout_s"]))
                phase = "measurement"
                deadline.require(config["trace"]["duration_s"] + config["engine"]["request_timeout_s"])
                request = lambda row: completion(engine.base_url, row["prompt"], row["max_output_tokens"],
                                                 deadline.timeout(config["engine"]["request_timeout_s"]))
                measured = run_trace(trace, request, PowerMeter(config["engine"]["gpu_index"], gpu_uuid=gpu_uuid))
                if measured["energy"].get("gpu_uuid") != gpu_uuid:
                    raise PowerError("Energy evidence came from a different GPU UUID")
                measured["hardware_sha256"] = digest(hardware)
                write_json(directory / "measurement.json", measured)
                runs.append(measured)
                calibrations.append(_calibration(measured["energy"]))
                event("repeat_completed", repeat=repeat + 1, status=measured["status"],
                      joules_per_output_token=measured["joules_per_output_token"],
                      p95_latency_s=measured["p95_latency_s"])
                # Measure the frozen bf16 default exactly once; never score final items here.
                if repeat == 0 and saved_baseline is None:
                    phase = "quality"
                    event("dev_baseline_started", items=len(dev))
                    baseline = _quality_baseline(engine, dev, config, deadline)
                    write_json(root / "dev-baseline.json", baseline)
                    failed = baseline["failed_requests"]
                    checks["quality_baseline"] = _gate("pass" if failed == 0 else "fail",
                        "Frozen bf16 default on 150 dev items; final eval untouched", evidence="dev-baseline.json")
        except TimeBudgetExceeded:
            raise
        except Exception as exc:
            if phase != "serving" and engine.metadata["identity_complete"]:
                checks["P1"] = _gate("pass", "Pinned bf16 served successfully", evidence="bf16-1/")
            failed_gate = ("P2" if isinstance(exc, PowerError) else "P4" if phase == "measurement"
                           else "quality_baseline" if phase == "quality" else "P1")
            if failed_gate == "P1" and repeat > 0 and checks["P1"]["status"] == "pass":
                # A later restart failure prevents the repeatability study; it
                # cannot erase already recorded successful pinned bf16 serving.
                failed_gate = "P4"
            checks[failed_gate] = _gate("fail", f"{phase} check failed: {type(exc).__name__}", evidence=f"bf16-{repeat + 1}/")
            return
        finally:
            write_json(directory / "engine-metadata.json", engine.metadata)
        if not engine.metadata["identity_complete"]:
            checks["P1"] = _gate("fail", "Serving worked but backend/footprint/version evidence is incomplete; inspect startup log")
            return
        checks["P1"] = _gate("pass", "Pinned bf16 served successfully with backend, footprint and hardware evidence", evidence="bf16-1/")
        if measured["status"] != "pass":
            checks["P4"] = _gate("fail", "A trace request failed or timed out; partial runs cannot pass")
            return
    idle_w = idle["joules"] / idle["duration_s"]
    load_w = statistics.median(row["joules"] / row["energy"]["duration_s"] for row in runs)
    granularity_ok = all(row["pass"] for row in calibrations)
    checks["P2"] = _gate("pass" if granularity_ok and load_w > idle_w else "fail",
        "Cumulative counter increased under load; boundary bound <1% and load exceeds idle" if granularity_ok and load_w > idle_w
        else "Lengthen trace or inspect telemetry: boundary granularity/load sanity check failed",
        idle_gpu_power_w=idle_w, load_gpu_power_w=load_w, calibrations=calibrations)
    j_cv = coefficient_of_variation([row["joules_per_output_token"] for row in runs])
    latency_cv = coefficient_of_variation([row["p95_latency_s"] for row in runs])
    tps_cv = coefficient_of_variation([row["output_tokens_per_second"] for row in runs])
    passed = j_cv < settings["cv_limit"] and latency_cv < settings["cv_limit"]
    checks["P4"] = _gate("pass" if passed else "fail",
        "Three frozen-trace repeats; require GPU J/token and p95 latency CV <3%",
        joules_per_token_cv=j_cv, p95_latency_cv=latency_cv, tokens_per_second_cv=tps_cv,
        repeats=3, trace_sha256=digest(trace))
    if not passed or checks["P2"]["status"] != "pass":
        return
    if config["try_fp8"]:
        deadline.require(2)
        bounded_config = {**engine_config, "startup_timeout_s": deadline.timeout(engine_config["startup_timeout_s"])}
        engine = ManagedEngine(bounded_config, root / "fp8-smoke", "fp8")
        try:
            event("engine_starting", dtype="fp8")
            with engine:
                smoke = completion(engine.base_url, "Reply with the single word ready.", 2048,
                                   deadline.timeout(config["engine"]["request_timeout_s"]), temperature=1)
                write_json(root / "fp8-smoke" / "smoke.json", smoke)
                if not smoke["text"].strip() or smoke["finish_reason"] != "stop":
                    raise ValueError("FP8 smoke completion did not finish with a nonempty final answer")
            checks["P1b"] = _gate("pass" if engine.metadata["identity_complete"] else "fail",
                "Online FP8 smoke only; energy benefit and quality equivalence have not been tested",
                quantization=config["engine"]["fp8_quantization"], evidence="fp8-smoke/")
        except TimeBudgetExceeded:
            raise
        except Exception as exc:
            checks["P1b"] = _gate("fail", f"Optional FP8 serving unavailable: {type(exc).__name__}; bf16 floor remains possible")
        finally:
            write_json(root / "fp8-smoke" / "engine-metadata.json", engine.metadata)


def _simulate(config, root, result, event):
    # Deterministic software fixture. It deliberately does not instantiate any
    # engine, NVML device, paid planner, or real cumulative budget ledger.
    checks = result["checks"]
    fixture = {"origin": "synthetic_fixture", "gpu": "SIMULATED: no GPU measurement", "paid_calls": 0}
    write_json(root / "hardware.json", fixture)
    prompts = ["Synthetic smoke prompt; never a real benchmark result."]
    trace = make_trace(prompts, config["trace"])
    write_json(root / "trace.json", trace)
    runs = []
    for repeat, factor in enumerate((1.0, 1.005, 0.995), 1):
        row = {"origin": "synthetic_fixture", "trace_sha256": digest(trace),
               "generated_tokens": 1024, "completed_requests": len(trace["requests"]),
               "joules": 100 * factor, "joules_per_output_token": 100 * factor / 1024,
               "joules_per_completed_request": 100 * factor / len(trace["requests"]),
               "p95_latency_s": 0.5 * factor, "all_requests_completed": True}
        write_json(root / f"fixture-{repeat}.json", row)
        runs.append(row)
        event("synthetic_repeat", repeat=repeat, **row)
    for name in ("P1", "P1b", "P2"):
        checks[name] = _gate("simulated", "Synthetic fixture only; this is not evidence that the hardware check passes")
    checks["P4"] = _gate("simulated", "Software fixture CV calculation only",
        joules_per_token_cv=coefficient_of_variation([r["joules_per_output_token"] for r in runs]),
        p95_latency_cv=coefficient_of_variation([r["p95_latency_s"] for r in runs]))
    checks["P3"] = _gate("skipped", "No provider access or ledger mutation in simulation")
    checks["quality_baseline"] = _gate("skipped", "No model quality claim from simulation")
    result["status"] = "simulation_complete"
