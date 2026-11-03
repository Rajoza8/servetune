"""Resumable v4 study: calibrate, freeze, map, A/B, search, confirm.

The controller calls fixed Python functions only. A proposal is data, never a
command. Completed trial directories are sealed and are never overwritten.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import time

from .artifacts import canonical, digest, file_hash, seal, timestamp, verify, write_json
from .deadline import SessionDeadline, TimeBudgetExceeded
from .ledger import Ledger
from .quality import evaluate_gate
from .workload import make_trace


PHASES = ("calibration", "map", "ab", "search", "confirmation")
KNOBS = ("max_num_seqs", "max_num_batched_tokens", "enable_chunked_prefill", "gpu_memory_utilization")


def _read(path):
    return json.loads(Path(path).read_text())


def _atomic(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def verify_trial(directory):
    from .study_runner import verify_trial as verify_runner_trial
    return verify_runner_trial(directory)


def initialize_study(directory, preflight_dir=None, data_dir=None, protocol=None, *, simulate=False):
    from .study_protocol import DEFAULT_STUDY, validate_study
    from .config import DEFAULT

    protocol = deepcopy(DEFAULT_STUDY if protocol is None else protocol)
    validate_study(protocol)
    root = Path(directory).resolve()
    if root.exists():
        raise FileExistsError("Study exists; resume it instead of resetting its evidence")
    preflight = None
    if not simulate:
        if preflight_dir is None or data_dir is None:
            raise ValueError("Live study requires a sealed passing preflight and its frozen data")
        preflight = verify(preflight_dir)
        required = ("P1", "P2", "P3", "P4", "quality_baseline")
        if (preflight.get("mode") != "live" or not preflight.get("live_preflight_passed")
                or any(preflight["checks"][key]["status"] != "pass" for key in required)):
            raise ValueError("Preflight must pass before any study work")
        base = _read(Path(preflight_dir) / "config.json")
        minimum_window = base["trace"]["duration_s"]
        if protocol["map"]["duration_s"] < minimum_window:
            raise ValueError("Comparison traces cannot be shorter than the passing P4 calibration")
    else:
        base = deepcopy(DEFAULT)
        base["engine"]["model_revision"] = "0" * 40
    root.mkdir(parents=True)
    write_json(root / "protocol.json", protocol)
    write_json(root / "base-config.json", base)
    source = root / "source"
    source.mkdir()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        shutil.copy2(path, source / path.name)
    if not simulate:
        shutil.copytree(preflight_dir, root / "preflight")
        shutil.copytree(data_dir, root / "data")
        write_json(root / "preflight-origin.json", {
            "manifest_sha256": file_hash(Path(preflight_dir) / "manifest.json"),
            "status": preflight["status"], "copied_source": "preflight",
            "reference_correct": _read(Path(preflight_dir) / "dev-baseline.json")["correct"],
            "fp8_supported": preflight["checks"]["P1b"]["status"] == "pass"})
    else:
        write_json(root / "preflight-origin.json", {"mode": "synthetic_fixture", "fp8_supported": True})
    initialization = {"schema_version": 1, "files": {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*")) if path.is_file()}}
    write_json(root / "initialization.json", initialization)
    write_json(root / "state.json", {
        "schema_version": 1, "created_at": timestamp(), "mode": "synthetic_fixture" if simulate else "live",
        "protocol_sha256": digest(protocol), "initialization_sha256": digest(initialization),
        "frozen_sha256": None, "status": "initialized", "completed_phases": [],
        "trials": [], "quality_cache": {}, "arms": {}, "active_arm": None,
        "floor": {"built": False, "reason": "Energy map and FP8 experiment have not run"}})
    _write_index(root, _read(root / "state.json"))
    return {"study": str(root), "mode": "synthetic_fixture" if simulate else "live", "status": "initialized"}


def _write_index(root, state, **extra):
    _atomic(root / "study.json", {
        "schema_version": 1, "mode": state["mode"], "status": state["status"],
        "created_at": state["created_at"], "updated_at": timestamp(),
        "protocol_sha256": state["protocol_sha256"], "completed_phases": state["completed_phases"],
        "trials": state["trials"], "floor": state["floor"],
        "arms": state.get("arms", {}), "budget": state.get("budget", {}),
        "slo_s": state.get("frozen", {}).get("slo_s"),
        "energy_label": "GPU energy (NVML)",
        "comparison_scope": "This physical GPU, pinned engine/model, frozen math workload and evaluation only",
        **extra})


class StudyController:
    def __init__(self, directory, *, max_runtime_s=None, ledger_path=None, runner=None, planner=None):
        from .study_protocol import validate_study
        from .study_runner import StudyRunner
        self.root = Path(directory).resolve()
        if (self.root / "manifest.json").exists():
            raise ValueError("Study is sealed; replay its results rather than adding measurements")
        self.protocol = validate_study(_read(self.root / "protocol.json"))
        self.state = _read(self.root / "state.json")
        if digest(self.protocol) != self.state["protocol_sha256"]:
            raise ValueError("Declared study protocol changed after initialization")
        self.simulate = self.state["mode"] == "synthetic_fixture"
        self.base = _read(self.root / "base-config.json")
        self._validate_initialization()
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.deadline = SessionDeadline(max_runtime_s)
        self.planner = planner
        self.runner = runner or StudyRunner(self.base, None if self.simulate else self.root / "data",
                                           None if self.simulate else self.root / "preflight",
                                           simulate=self.simulate)
        self.prompts = (["Synthetic math performance prompt"] if self.simulate
                        else _read(self.root / "data/prompts.json"))
        self.fp8 = bool(_read(self.root / "preflight-origin.json").get("fp8_supported"))
        self.last_trial_cost_s = self.protocol["tuning"]["trial_estimate_s"]
        self.final_reserve_s = 9 * 3600 if not self.simulate else 1
        self.state.setdefault("runtime_sessions", [])
        self.runtime_started = time.monotonic()
        # A crashed allocated interval is never free. Unknown downtime is charged
        # conservatively and explicitly marked; a measured comparison is qualified.

    def _validate_initialization(self):
        initialization = _read(self.root / "initialization.json")
        if (initialization.get("schema_version") != 1
                or digest(initialization) != self.state.get("initialization_sha256")
                or not isinstance(initialization.get("files"), dict)):
            raise ValueError("Study initialization/source binding changed")
        scientific_sources = {"study.py", "study_runner.py", "study_protocol.py", "study_planner.py",
                              "engine.py", "quality.py", "workload.py", "power.py", "ledger.py",
                              "planner.py", "timing.py", "deadline.py", "config.py", "evidence.py",
                              "preflight.py", "artifacts.py", "hardware.py", "data.py"}
        for name, checksum in initialization["files"].items():
            relative = Path(name)
            path = self.root / relative
            if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                    or not path.resolve().is_relative_to(self.root) or not path.is_file()
                    or file_hash(path) != checksum):
                raise ValueError("Frozen initialization data, source snapshot, or identity changed")
            if relative.parts[0] == "source" and relative.name in scientific_sources:
                if file_hash(Path(__file__).parent / relative.name) != checksum:
                    raise ValueError("Scientific implementation changed since study initialization")
        if _read(self.root / "base-config.json") != self.base:
            raise ValueError("Study base configuration changed")

    def _load_trace(self, load):
        relative = Path(load["trace"])
        path = self.root / relative
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or not path.resolve().is_relative_to(self.root / "traces") or not path.is_file()):
            raise ValueError("Frozen load trace is missing or outside its trace directory")
        trace = _read(path)
        expected_settings = {"seed": self.protocol["workload"]["seed"],
            "duration_s": self.protocol["map"]["duration_s"], "arrival_rate": load["arrival_rate"],
            "max_output_tokens": self.protocol["workload"]["max_output_tokens"],
            "max_requests": self.protocol["workload"]["max_requests"]}
        if (digest(trace) != load["trace_sha256"]
                or digest(trace) != digest(make_trace(self.prompts, expected_settings))):
            raise ValueError("Frozen load trace no longer matches the declared workload")
        return trace

    def _validate_frozen(self):
        frozen = _read(self.root / "frozen.json")
        if (not self.state.get("frozen_sha256")
                or digest(frozen) != self.state["frozen_sha256"]
                or frozen.get("protocol_sha256") != self.state["protocol_sha256"]):
            raise ValueError("Frozen workload declaration changed or lost its binding")
        if (frozen.get("quality_reference_correct") != self.runner.baseline_score["correct"]
                or frozen.get("slo_s") != self.protocol["tuning"]["slo_s"]):
            raise ValueError("Frozen quality reference or SLO changed")
        from .study_protocol import validate_knobs
        validate_knobs(frozen["engine_defaults"], self.protocol["space"])
        for load in frozen["loads"]:
            self._load_trace(load)
        self.state["frozen"] = frozen
        return frozen

    def _cache_trial_quality(self, result, name, engine, dtype):
        score = result.get("quality")
        split = result.get("quality_split")
        if score is None:
            return
        if split not in ("dev", "final") or score.get("items") != (150 if split == "dev" else 300):
            raise ValueError("Trial quality evidence has the wrong frozen split size")
        gate = evaluate_gate(score, self.runner.baseline_score, "dev") if split == "dev" else None
        if split == "dev" and result.get("quality_gate") != gate:
            raise ValueError("Stored development gate disagrees with frozen scoring")
        quality_key = digest({"engine": engine, "dtype": dtype, "split": split})
        value = {"trial": name, "score": score, "gate": gate}
        prior = self.state["quality_cache"].get(quality_key)
        if prior is not None and (prior["score"] != score or prior.get("gate") != gate):
            if split == "final":
                raise ValueError("A final evaluation was measured more than once for the same configuration")
        # Every tuning candidate is gated anew. This derived cache follows the
        # latest dev attempt; immutable raw attempts retain every earlier score.
        # The original bf16 reference is separate and is never replaced here.
        self.state["quality_cache"][quality_key] = value

    def _restore_quality_cache(self):
        self.state["quality_cache"] = {}
        known = {entry["id"] for entry in self.state["trials"]}
        # A sealed trial may have completed just before its mutable index update.
        # Recover its predeclared identity, without executing or rewriting it.
        for path in sorted((self.root / "trial-intents").glob("*.json")):
            intent = _read(path)
            name = intent.get("id")
            if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
                raise ValueError("Invalid retained trial identity")
            trial_path = self.root / "trials" / name
            if name not in known and (trial_path / "manifest.json").exists():
                trial = verify_trial(trial_path)
                if (intent.get("config_sha256") != trial.get("config_sha256")
                        or intent.get("trace_sha256") != trial.get("trace_sha256")
                        or intent.get("dtype") != trial.get("dtype")):
                    raise ValueError("Retained trial intent disagrees with sealed evidence")
                self.state["trials"].append({key: intent[key] for key in
                    ("id", "path", "phase", "arm", "load_label", "config_label")})
                known.add(name)
        for entry in self.state["trials"]:
            trial = verify_trial(self.root / entry["path"])
            self._cache_trial_quality(trial, entry["id"], trial["config"], trial["dtype"])
            self._attach_quality(entry, trial, trial["config"], trial["dtype"])

    def _attach_quality(self, entry, result, engine, dtype):
        cached = self._quality_cached(engine, dtype)
        if result.get("quality") is not None and result.get("quality_split") == "dev":
            cached = {"trial": entry["id"], "score": result["quality"], "gate": result.get("quality_gate")}
        if cached is not None:
            entry["quality_gate"] = deepcopy(cached.get("gate"))
            entry["quality_summary"] = {key: cached["score"][key] for key in
                ("correct", "items", "failed_requests", "truncated_answers")}
            entry["quality_source"] = ("preflight/dev-baseline.json" if cached["trial"] == "preflight"
                                       else f"trials/{cached['trial']}/trial.json")
        elif result.get("quality") is not None:
            entry["quality_summary"] = {key: result["quality"][key] for key in
                ("correct", "items", "failed_requests", "truncated_answers")}

    def _recover_interrupted_allocation(self):
        if self.state.get("active_arm"):
            active = self.state["active_arm"]
            arm = self.state["arms"][active["arm"]]
            charge = max(0, time.time() - active["started_epoch"])
            arm["elapsed_s"] += charge
            arm.setdefault("interruptions", []).append({"seconds_upper_bound": charge,
                "reason": "Interrupted controller allocation; elapsed wall time conservatively retained"})
            self.state["active_arm"] = None
            self._save()

    def _save(self):
        _atomic(self.root / "state.json", self.state)
        _write_index(self.root, self.state)

    def event(self, event, **details):
        row = {"at": timestamp(), "event": event, **details}
        with (self.root / "events.jsonl").open("a") as stream:
            stream.write(canonical(row).decode() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps(row, allow_nan=False), flush=True)

    def _engine(self, knobs=None, *, defaults=False):
        config = deepcopy(self.runner.base_engine_config)
        config["use_engine_defaults"] = defaults
        if knobs is not None and not defaults:
            config.update({key: knobs[key] for key in KNOBS})
        return config

    def _trace(self, label, rate, *, calibration=False):
        path = self.root / "traces" / (label + ".json")
        settings = {"seed": self.protocol["workload"]["seed"],
                    "duration_s": self.protocol["calibration"]["duration_s"] if calibration else self.protocol["map"]["duration_s"],
                    "arrival_rate": rate,
                    "max_output_tokens": self.protocol["workload"]["max_output_tokens"],
                    "max_requests": (self.protocol["calibration"]["max_requests"] if calibration
                                     else self.protocol["workload"]["max_requests"])}
        trace = make_trace(self.prompts, settings)
        if path.exists():
            if digest(_read(path)) != digest(trace):
                raise ValueError("Frozen trace changed")
        else:
            write_json(path, trace)
        return trace

    def _trial(self, name, engine, dtype, trace, *, phase, arm=None, load_label=None,
               config_label=None, quality_split=None, deadline=None):
        if (not isinstance(name, str) or not name or Path(name).name != name
                or name in (".", "..") or phase not in (*PHASES, "shared_baseline")):
            raise ValueError("Trial IDs and phases must be fixed safe values")
        path = self.root / "trials" / name
        entry = {"id": name, "path": f"trials/{name}", "phase": phase, "arm": arm,
                 "load_label": load_label, "config_label": config_label or name}
        intent_path = self.root / "trial-intents" / (name + ".json")
        intent = {**entry, "dtype": dtype, "config_sha256": digest(engine),
                  "trace_sha256": digest(trace), "quality_split": quality_split}
        if intent_path.exists():
            original_intent = _read(intent_path)
            compare = {key: value for key, value in intent.items() if key != "quality_split"}
            if (any(original_intent.get(key) != value for key, value in compare.items())
                    or (quality_split is not None and quality_split != original_intent.get("quality_split"))):
                raise ValueError("A fixed trial ID cannot be reassigned to another protocol or evaluation split")
        if path.exists():
            if not intent_path.exists():
                raise ValueError("Existing trial lacks its predeclared controller identity")
            result = verify_trial(path)
            if (result.get("dtype") != dtype or result.get("trace_sha256") != digest(trace)
                    or result.get("config_sha256") != digest(engine)
                    or (quality_split is not None and result.get("quality_split") != quality_split)):
                raise ValueError("Existing trial does not match the declared configuration/trace")
            self._cache_trial_quality(result, name, engine, dtype)
            self._attach_quality(entry, result, engine, dtype)
            prior = next((row for row in self.state["trials"] if row["id"] == name), None)
            if prior is None:
                self.state["trials"].append(entry)
            else:
                prior.update({key: value for key, value in entry.items() if key.startswith("quality_")})
            self._save()
            return result
        current_deadline = deadline or self.deadline
        estimate = (1 if self.simulate else trace["settings"]["duration_s"] + 600
                    + (2100 if quality_split == "dev" else 4200 if quality_split == "final" else 0))
        current_deadline.require(estimate)
        if not intent_path.exists():
            write_json(intent_path, intent)
        if quality_split == "final":
            claim_path = self.root / "final-claims" / (digest({"engine": engine, "dtype": dtype}) + ".json")
            if claim_path.exists():
                raise ValueError("Final evaluation already claimed; an interrupted final set cannot be silently retried")
            write_json(claim_path, {"trial": name, "claimed_at": timestamp(), "single_use": True})
        self.event("trial_started", **entry, dtype=dtype, quality_split=quality_split)
        result = self.runner.measure(path, engine, dtype, trace, deadline=current_deadline,
                                     quality_split=quality_split)
        verify_trial(path)
        self._cache_trial_quality(result, name, engine, dtype)
        self._attach_quality(entry, result, engine, dtype)
        self.state["trials"].append(entry)
        self._save()
        self.event("trial_finished", id=name, phase=phase, arm=arm, status=result["status"],
                   allocated_seconds=result.get("allocated_seconds"))
        return result

    def _quality_cached(self, engine, dtype):
        result = self.state["quality_cache"].get(digest({"engine": engine, "dtype": dtype, "split": "dev"}))
        if result is None and dtype == "bf16" and engine.get("use_engine_defaults") is True:
            baseline = self.runner.baseline_score
            result = {"trial": "preflight", "score": baseline,
                      "gate": evaluate_gate(baseline, baseline, "dev")}
        return result

    def calibrate(self):
        if (self.root / "frozen.json").exists() and self.state.get("frozen_sha256"):
            self._validate_frozen()
            return
        rates = self.protocol["calibration"]["rates"]
        passing, observations = [], []
        effective = None
        for index, rate in enumerate(rates):
            trace = self._trace(f"pilot-{index:02d}", rate, calibration=True)
            trial = self._trial(f"pilot-{index:02d}", self._engine(defaults=True), "bf16", trace,
                                phase="calibration", load_label=f"pilot-{rate:g}", config_label="bf16-default")
            measurement = trial.get("measurement") or {}
            if effective is None:
                metadata = trial.get("engine_metadata") or {}
                effective = metadata.get("effective_tuning_values")
            if self.simulate:
                effective = {key: self.runner.base_engine_config[key] for key in KNOBS}
            passed = (self._operational(trial) and measurement.get("all_requests_completed")
                      and measurement.get("p95_latency_s", float("inf")) <= self.protocol["tuning"]["slo_s"])
            observations.append({"arrival_rate": rate, "status": trial["status"], "within_slo": passed,
                                 "p95_latency_s": measurement.get("p95_latency_s")})
            if passed:
                passing.append(rate)
            else:
                break
        if not passing:
            raise ValueError("No default bf16 load passed; no comparison workload can be frozen")
        if not isinstance(effective, dict) or any(key not in effective for key in KNOBS):
            raise ValueError("Actual vLLM default knobs were not observed; refuse to invent a search baseline")
        from .study_protocol import validate_knobs
        validate_knobs(effective, self.protocol["space"])
        saturation_rate = observations[-1]["arrival_rate"]
        saturation_observed = not observations[-1]["within_slo"]
        anchor = passing[-1]
        # Near-load target uses the highest observed passing rate. If a failure
        # brackets saturation, its evidence is retained; otherwise report a bound.
        loads = []
        max_fraction = max(self.protocol["map"]["load_fractions"])
        for index, fraction in enumerate(self.protocol["map"]["load_fractions"]):
            rate = anchor * fraction / max_fraction
            label = f"load-{index + 1}"
            trace = self._trace(label, rate)
            loads.append({"label": label, "arrival_rate": rate, "trace": f"traces/{label}.json",
                          "declared_fraction": fraction, "fraction_of_highest_passing": fraction / max_fraction,
                          "trace_sha256": digest(trace)})
        cv = 0.0
        if not self.simulate:
            check = _read(self.root / "preflight/preflight.json")["checks"]["P4"]
            energy_cvs = [value for key, value in check.items() if "cv" in key
                          and any(term in key for term in ("joule", "energy"))
                          and type(value) in (int, float) and math.isfinite(value) and value >= 0]
            if not energy_cvs:
                raise ValueError("Passing P4 is missing its observed energy CV")
            cv = max(energy_cvs)
        frozen = {"created_at": timestamp(), "protocol_sha256": digest(self.protocol),
                  "loads": loads, "tuning_load": loads[-1]["label"],
                  "slo_s": self.protocol["tuning"]["slo_s"], "engine_defaults": effective,
                  "saturation": {"observed_failure_bracket": saturation_observed,
                                 "highest_passing_rate": anchor, "last_tested_rate": saturation_rate,
                                 "observations": observations,
                                 "limitation": None if saturation_observed else "No failing rate observed; saturation is only lower-bounded"},
                  "preflight_observed_cv": cv,
                  "quality_reference_correct": self.runner.baseline_score["correct"],
                  "tuning_dtype": "declared after FP8 A/B quality, before either arm",
                  "arm_fairness": "Same measured start, space, frozen trace, SLO, quality gate and allocated time; isolated histories"}
        frozen_path = self.root / "frozen.json"
        if frozen_path.exists():
            prior = _read(frozen_path)
            if ({key: value for key, value in prior.items() if key != "created_at"}
                    != {key: value for key, value in frozen.items() if key != "created_at"}):
                raise ValueError("Unbound frozen declaration differs from deterministic completed calibration")
            frozen = prior  # Recover a crash after exclusive write, before state persistence.
        else:
            write_json(frozen_path, frozen)
        self.state["frozen"] = frozen
        self.state["frozen_sha256"] = digest(frozen)
        self._save()
        self.event("workloads_frozen", loads=loads, engine_defaults=effective)

    def _summary(self, trials, repeats):
        from .study_protocol import summarize_repeats
        measurements = [deepcopy(row.get("measurement") or {"status": row["status"]}) for row in trials]
        for trial, measurement in zip(trials, measurements):
            gate = trial.get("quality_gate")
            if gate is None and trial.get("config") is not None and trial.get("dtype") is not None:
                cached = self._quality_cached(trial["config"], trial["dtype"])
                gate = cached.get("gate") if cached else None
            if not self._operational(trial) or (gate or {}).get("passed") is False:
                measurement["status"] = "fail"
        if self.simulate:
            for measurement in measurements:
                if measurement.get("origin") == "synthetic_fixture" and measurement.get("status") != "fail":
                    measurement["status"] = "pass"
        return summarize_repeats(measurements, expected_repeats=repeats)

    def _operational(self, trial):
        return trial.get("status") == "pass" or (self.simulate and trial.get("status") == "synthetic_fixture")

    def energy_map(self):
        frozen = self.state["frozen"]
        default_knobs = frozen["engine_defaults"]
        choices = list(dict.fromkeys([default_knobs["max_num_seqs"]] + self.protocol["map"]["max_num_seqs"]))
        # Keep the declared small grid: defaults plus the predeclared alternatives.
        summaries = []
        for load in frozen["loads"]:
            trace = self._load_trace(load)
            for dtype in (["bf16", "fp8"] if self.fp8 else ["bf16"]):
                for seqs in choices:
                    is_default = seqs == default_knobs["max_num_seqs"]
                    knobs = {**default_knobs, "max_num_seqs": seqs}
                    engine = self._engine(knobs, defaults=is_default)
                    label = f"{dtype}-default" if is_default else f"{dtype}-seqs-{seqs}"
                    repeats = []
                    for repeat in range(self.protocol["map"]["repeats"]):
                        # bf16 default's once-measured reference is frozen; every
                        # other unique config obtains its own dev gate once here.
                        quality = None if (dtype == "bf16" and is_default) or self._quality_cached(engine, dtype) else "dev"
                        repeats.append(self._trial(f"map-{load['label']}-{label}-{repeat:02d}", engine, dtype, trace,
                            phase="map", load_label=load["label"], config_label=label, quality_split=quality))
                    summaries.append({"load": load["label"], "config_label": label, "dtype": dtype,
                                      "summary": self._summary(repeats, self.protocol["map"]["repeats"]),
                                      "quality": self._quality_cached(engine, dtype)})
        _atomic(self.root / "map.json", {"grid": summaries, "failing_loads_retained": True})

    def ab(self):
        frozen = self.state["frozen"]
        load = next(row for row in frozen["loads"] if row["label"] == frozen["tuning_load"])
        trace = self._load_trace(load)
        records = {"bf16": [], "fp8": []}
        if not self.fp8:
            _atomic(self.root / "ab.json", {"status": "skipped", "reason": "P1b did not pass", "fp8_quality_passed": False})
            return
        for repeat in range(5):
            for dtype in ("bf16", "fp8"):
                engine = self._engine(defaults=True)
                quality = "dev" if dtype == "fp8" and not self._quality_cached(engine, dtype) else None
                records[dtype].append(self._trial(f"ab-{repeat:02d}-{dtype}", engine, dtype, trace,
                    phase="ab", load_label=load["label"], config_label=f"{dtype}-default", quality_split=quality))
        quality = self._quality_cached(self._engine(defaults=True), "fp8")
        gate_passed = bool(quality and quality.get("gate", {}).get("passed"))
        summaries = {dtype: self._summary(rows, 5) for dtype, rows in records.items()}
        _atomic(self.root / "ab.json", {"status": "complete", "summaries": summaries,
            "fp8_quality_passed": gate_passed, "fp8_quality": quality,
            "order": [dtype for _ in range(5) for dtype in ("bf16", "fp8")],
            "headline": False, "claim": "Preliminary A/B; headline numbers require fresh final confirmation"})

    def _update_floor(self):
        complete = all(name in self.state["completed_phases"] for name in ("map", "ab"))
        verified_map = [row for row in self.state["trials"] if row["phase"] == "map"]
        # Saturated / failed load points are an outcome, not deleted evidence.
        valid_dtypes = set()
        for entry in verified_map:
            trial = verify_trial(self.root / entry["path"])
            measurement = trial.get("measurement") or {}
            if (trial.get("mode") == "live" and (trial.get("calibration") or {}).get("pass") is True
                    and measurement.get("status") == "pass" and measurement.get("all_requests_completed")
                    and measurement.get("joules_per_output_token", 0)):
                valid_dtypes.add(trial["dtype"])
        has_measured_map = "bf16" in valid_dtypes and (not self.fp8 or "fp8" in valid_dtypes)
        self.state["floor"] = {"built": bool(complete and not self.simulate and has_measured_map),
            "reason": ("Synthetic workflow fixture only; no live energy-map floor is established" if self.simulate
                       else "Map/A/B phase not yet complete" if not complete
                       else "Frozen bf16 map, conditional FP8 map/A/B, sealed raw records and offline replay available" if has_measured_map
                       else "Map/A/B attempts retained, but required dtypes lack a complete measured energy point"),
            "final_confirmation_complete": "confirmation" in self.state["completed_phases"],
            "fp8_required": self.fp8, "recorded_map_trials": len(verified_map)}
        self._save()

    def _load_history(self, arm):
        path = self.root / "arms" / arm / "history.json"
        return _read(path) if path.exists() else []

    def _save_history(self, arm, history):
        path = self.root / "arms" / arm / "history.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic(path, history)

    def _allocation(self, arm):
        row = self.state["arms"][arm]
        return max(0, row["budget_s"] - row["elapsed_s"])

    def search(self):
        from .study_protocol import acceptance, apply_proposal, random_proposal, validate_knobs
        from .study_planner import propose_spark
        frozen = self.state["frozen"]
        ab = _read(self.root / "ab.json")
        dtype = "fp8" if ab.get("fp8_quality_passed") else "bf16"
        load = next(row for row in frozen["loads"] if row["label"] == frozen["tuning_load"])
        trace = self._load_trace(load)
        start = frozen["engine_defaults"]
        unmeasured_baseline = sum(not (self.root / "trials" / f"shared-start-{repeat:02d}" / "manifest.json").exists()
                                  for repeat in range(3))
        if not self.simulate and unmeasured_baseline:
            self.deadline.require(self.final_reserve_s + unmeasured_baseline *
                                  (trace["settings"]["duration_s"] + 600))
        baseline_trials = [self._trial(f"shared-start-{repeat:02d}", self._engine(defaults=True), dtype, trace,
                                      phase="shared_baseline", load_label=load["label"], config_label=f"{dtype}-default")
                           for repeat in range(3)]
        baseline = self._summary(baseline_trials, 3)
        if baseline.get("status") != "pass":
            raise ValueError("Shared tuning baseline is incomplete")
        observed_cv = max(frozen["preflight_observed_cv"], baseline.get("joules_per_token_cv") or 0)
        declaration_path = self.root / "tuning-declaration.json"
        declaration_identity = {"dtype": dtype, "baseline": baseline, "baseline_config": start,
            "space": self.protocol["space"], "slo_s": frozen["slo_s"],
            "frozen_before_first_arm": True,
            "quality_reference": "once-measured bf16 default, not the tuning dtype score",
            "observed_cv": observed_cv, "confirmation_time_reserved_s": self.final_reserve_s}
        saved_declaration = _read(declaration_path) if declaration_path.exists() else None
        if saved_declaration is not None:
            if (any(saved_declaration.get(key) != value for key, value in declaration_identity.items())
                    or type(saved_declaration.get("arm_budget_s")) not in (int, float)
                    or not math.isfinite(saved_declaration["arm_budget_s"])
                    or not 0 <= saved_declaration["arm_budget_s"] <= self.protocol["tuning"]["arm_budget_s"]):
                raise ValueError("Frozen tuning declaration changed or disagrees with its shared baseline")
        if not self.state["arms"]:
            # Reserve confirmation before splitting remaining time equally.
            remaining_for_search = self.deadline.remaining() - self.final_reserve_s
            budget = min(self.protocol["tuning"]["arm_budget_s"], max(0, remaining_for_search / 2))
            if self.simulate:
                budget = self.protocol["tuning"]["arm_budget_s"]
            if saved_declaration is not None:
                budget = saved_declaration["arm_budget_s"]
            else:
                write_json(declaration_path, {**declaration_identity, "arm_budget_s": budget})
            self.state["arms"] = {arm: {"budget_s": budget, "elapsed_s": 0, "planner_wait_s": 0,
                "best_config": start, "best_summary": baseline, "trials": 0, "status": "ready",
                "last_trial_cost_s": self.protocol["tuning"]["trial_estimate_s"]} for arm in ("R", "S")}
            self._save()
        elif (saved_declaration is None or any(account["budget_s"] != saved_declaration["arm_budget_s"]
                                              for account in self.state["arms"].values())):
            raise ValueError("Arm budgets no longer match the original equal-budget declaration")
        max_trials = self.protocol["tuning"]["max_trials"]
        for turn in range(max_trials):
            active_this_turn = False
            eligible = []
            for arm in ("R", "S"):
                account = self.state["arms"][arm]
                estimate = 1 if self.simulate else max(account["last_trial_cost_s"] * 1.15,
                                                       self.protocol["tuning"]["trial_estimate_s"])
                if account["status"] not in ("stopped", "complete") and account["trials"] <= turn and self._allocation(arm) >= estimate:
                    eligible.append((arm, estimate))
            if (len(eligible) == 2 and self.deadline.remaining()
                    < self.final_reserve_s + sum(estimate for _, estimate in eligible)):
                for arm, _ in eligible:
                    self.state["arms"][arm].update(status="stopped",
                        stop_reason="Cannot admit another balanced arm pair while preserving final confirmation")
                self._save()
                break
            for arm in ("R", "S"):
                account = self.state["arms"][arm]
                if account["status"] in ("stopped", "complete") or account["trials"] > turn:
                    continue
                estimate = 1 if self.simulate else max(account["last_trial_cost_s"] * 1.15, self.protocol["tuning"]["trial_estimate_s"])
                if self._allocation(arm) < estimate or self.deadline.remaining() < estimate + self.final_reserve_s:
                    account.update(status="stopped", stop_reason="Cannot fit another complete trial while preserving confirmation")
                    self._save()
                    continue
                active_this_turn = True
                started = time.monotonic()
                self.state["active_arm"] = {"arm": arm, "started_epoch": time.time(), "turn": turn}
                self._save()
                history = self._load_history(arm)
                trial_id = f"search-{arm}-{turn:03d}"
                proposal_path = self.root / "proposals" / trial_id
                row = {"arm": arm, "trial": turn, "started_at": timestamp(), "config": account["best_config"]}
                planner_started = time.monotonic()
                planner_seconds = None
                try:
                    if arm == "R":
                        proposal = random_proposal(account["best_config"], self.protocol["space"],
                                                   random.Random(self.protocol["tuning"]["seed"] + turn))
                        candidate = validate_knobs(proposal["config"], self.protocol["space"])
                        planning = {"status": "pass", "proposal": proposal, "next_config": candidate}
                        write_json(proposal_path / "random-proposal.json", planning)
                    elif self.simulate:
                        proposal = random_proposal(account["best_config"], self.protocol["space"], random.Random(turn + 17))
                        diff = {next(iter(proposal["diff"])): next(iter(proposal["diff"].values()))}
                        proposal = {"hypothesis": "Synthetic planner fixture", "expected_effect": "No measured claim", "diff": diff}
                        candidate = apply_proposal(account["best_config"], proposal, self.protocol["space"])
                        planning = {"status": "pass", "proposal": proposal, "next_config": candidate}
                        write_json(proposal_path / "synthetic-proposal.json", planning)
                    else:
                        if self.ledger_path is None:
                            raise ValueError("Spark requires the cumulative ServeTune provider ledger")
                        context = {"config": start, "summary": baseline, "slo_s": frozen["slo_s"],
                            "observed_cv": observed_cv, "reference_correct": self.runner.baseline_score["correct"],
                            "reference_items": 150, "dtype": dtype,
                            "remaining_budget_s": self._allocation(arm), "remaining_trials": max_trials - turn}
                        planning = (self.planner or propose_spark)(account["best_config"], history,
                            self.protocol["space"], context, self.ledger_path, proposal_path,
                            timeout_s=min(60, self._allocation(arm) - 30))
                        planner_seconds = time.monotonic() - planner_started
                        if planning["status"] != "pass":
                            raise ValueError("Spark proposal rejected or provider budget unavailable")
                        proposal = planning["proposal"]
                        candidate = apply_proposal(account["best_config"], proposal, self.protocol["space"])
                    planner_seconds = time.monotonic() - planner_started
                    row.update(proposal=proposal, next_config=candidate, planner_wait_seconds=planner_seconds)
                    remaining = min(self._allocation(arm) - (time.monotonic() - started),
                                    self.deadline.remaining() - self.final_reserve_s)
                    trial_deadline = SessionDeadline(remaining if not self.simulate else None)
                    engine = self._engine(candidate)
                    trials = []
                    for repeat in range(3):
                        trial = self._trial(f"{trial_id}-{repeat:02d}", engine, dtype, trace,
                            phase="search", arm=arm, load_label=load["label"], config_label=trial_id,
                            quality_split="dev" if repeat == 0 else None, deadline=trial_deadline)
                        trials.append(trial)
                        if not self._operational(trial) or (repeat == 0 and not (trial.get("quality_gate") or {}).get("passed")):
                            break
                    summary = self._summary(trials, 3)
                    gate = trials[0].get("quality_gate") or {"passed": False}
                    decision = acceptance(summary, account["best_summary"], baseline, gate,
                        slo_s=frozen["slo_s"], observed_cv=observed_cv)
                    if time.monotonic() - started > self._allocation(arm):
                        decision = {"accepted": False, "reasons": ["Partial or over-budget trial discarded at cutoff"]}
                    row.update(summary=summary, quality_gate=gate, decision=decision)
                    for entry in self.state["trials"]:
                        if entry["id"].startswith(trial_id + "-"):
                            entry.update(proposal=deepcopy(proposal), decision=deepcopy(decision),
                                         length_drift=deepcopy(decision.get("length_drift")))
                    if decision["accepted"]:
                        account.update(best_config=candidate, best_summary=summary)
                    account["last_trial_cost_s"] = max(account["last_trial_cost_s"], time.monotonic() - started)
                except TimeBudgetExceeded:
                    row.update(decision={"accepted": False, "reasons": ["Deadline; partial trial discarded"]})
                    account.update(status="stopped", stop_reason="Deadline")
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    row.update(decision={"accepted": False, "reasons": ["Proposal or trial failed validation"]}, error_type=type(exc).__name__)
                    if arm == "S" and not self.simulate and self.ledger_path is not None:
                        budget = Ledger(self.ledger_path).summary()
                        if budget["blocked"] or "meta" in budget["exhausted_providers"]:
                            account.update(status="stopped", stop_reason="Meta cumulative spending cap")
                finally:
                    if planner_seconds is None:
                        planner_seconds = time.monotonic() - planner_started
                    account["planner_wait_s"] += planner_seconds
                    row["planner_wait_seconds"] = planner_seconds
                    allocated = time.monotonic() - started
                    account["elapsed_s"] += allocated
                    account["trials"] += 1
                    row["allocated_seconds"] = allocated
                    row["remaining_budget_seconds"] = self._allocation(arm)
                    row["ended_at"] = timestamp()
                    history.append(row)
                    self._save_history(arm, history)
                    self.state["active_arm"] = None
                    self._save()
                    self.event("arm_trial_decided", arm=arm, trial=turn, allocated_seconds=allocated,
                               decision=row.get("decision"))
            if not active_this_turn:
                break
        for account in self.state["arms"].values():
            if account["status"] == "ready":
                account["status"] = "complete"
        self._save()

    def confirm(self):
        frozen = self.state["frozen"]
        load = next(row for row in frozen["loads"] if row["label"] == frozen["tuning_load"])
        trace = self._load_trace(load)
        configs = [{"label": "bf16-default", "dtype": "bf16", "engine": self._engine(defaults=True)}]
        if self.fp8:
            configs.append({"label": "fp8-default", "dtype": "fp8", "engine": self._engine(defaults=True)})
        dtype = _read(self.root / "tuning-declaration.json")["dtype"]
        default_knobs = frozen["engine_defaults"]
        for arm in ("R", "S"):
            knobs = self.state["arms"][arm]["best_config"]
            configs.append({"label": f"{arm}-winner", "dtype": dtype,
                            "engine": self._engine(knobs, defaults=knobs == default_knobs)})
        unique, aliases = [], {}
        for config in configs:
            key = digest({"dtype": config["dtype"], "engine": config["engine"]})
            previous = next((row for row in unique if row["key"] == key), None)
            if previous:
                aliases[config["label"]] = previous["label"]
            else:
                unique.append({**config, "key": key})
        results = {row["label"]: [] for row in unique}
        quality = {}
        repeats = self.protocol["confirmation"]["repeats"]
        # Alternate configurations for every fresh performance repeat. Only the
        # final round uses each config's single untouched final evaluation.
        for repeat in range(repeats):
            for config in unique:
                label = config["label"]
                trial = self._trial(f"confirmation-{label}-{repeat:02d}", config["engine"], config["dtype"], trace,
                    phase="confirmation", load_label=load["label"], config_label=label,
                    quality_split="final" if repeat == repeats - 1 else None)
                results[label].append(trial)
                if repeat == repeats - 1 and trial.get("quality") is not None:
                    quality[label] = trial["quality"]
        baseline = quality.get("bf16-default")
        paired = []
        if baseline is not None and baseline.get("failed_requests") == 0:
            for label, score in quality.items():
                paired.append({"config_label": label, **evaluate_gate(score, baseline, "final")})
        for alias, target in aliases.items():
            if target in quality:
                quality[alias] = quality[target]
        summaries = {label: self._summary(rows, repeats) for label, rows in results.items()}
        complete = (baseline is not None and baseline.get("failed_requests") == 0
                    and len(quality) == len(configs) and all(row.get("status") == "pass" for row in summaries.values()))
        # Gate failures are an honest completed outcome, never grounds to rerun
        # the held-out set or choose a different winner using its answers.
        _atomic(self.root / "confirmation.json", {"status": "complete" if complete else "incomplete",
            "summaries": summaries, "quality_results": quality, "baseline_label": "bf16-default",
            "paired_quality": paired, "aliases": aliases, "single_use_final_set": True,
            "selected_trial_ids": [entry["id"] for entry in self.state["trials"] if entry["phase"] == "confirmation"],
            "headline_source": "fresh confirmation only", "energy_label": "GPU energy (NVML)"})
        if not complete:
            raise ValueError("Final confirmation incomplete; no substitute headline measurements allowed")

    def run(self, phase="all"):
        if phase != "all" and phase not in PHASES:
            raise ValueError("Unknown study phase")
        lock_path = self.root.parent / (self.root.name + ".lock")
        with lock_path.open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Another controller may have completed or advanced the study after
            # this object was constructed. Reload only while holding the lock.
            if (self.root / "manifest.json").exists():
                raise ValueError("Study was sealed by another controller; no metadata may be changed")
            self.state = _read(self.root / "state.json")
            self.state.setdefault("runtime_sessions", [])
            if digest(self.protocol) != self.state.get("protocol_sha256"):
                raise ValueError("Declared study protocol changed before locked execution")
            self._validate_initialization()
            self._restore_quality_cache()
            if "calibration" in self.state["completed_phases"]:
                self._validate_frozen()
            self._recover_interrupted_allocation()
            if phase in self.state["completed_phases"]:
                return _read(self.root / "study.json")
            next_phase = next((name for name in PHASES if name not in self.state["completed_phases"]), None)
            if phase != "all" and phase != next_phase:
                raise ValueError("Complete prerequisite phases first")
            try:
                self.state["status"] = "running"
                self._save()
                for name in PHASES:
                    if name in self.state["completed_phases"]:
                        continue
                    if phase != "all" and name != phase:
                        raise ValueError("Complete prerequisite phases first")
                    self.event("phase_started", phase=name)
                    {"calibration": self.calibrate, "map": self.energy_map, "ab": self.ab,
                     "search": self.search, "confirmation": self.confirm}[name]()
                    self.state["completed_phases"].append(name)
                    self._update_floor()
                    self.event("phase_completed", phase=name)
                    if phase != "all":
                        break
                complete = all(name in self.state["completed_phases"] for name in PHASES)
                self.state["status"] = ("simulation_complete" if self.simulate else "complete") if complete else "paused_at_phase_boundary"
                if not self.simulate and self.ledger_path:
                    self.state["budget"] = Ledger(self.ledger_path).summary()
                self.state["runtime_sessions"].append({"ended_at": timestamp(), "allocated_seconds": time.monotonic() - self.runtime_started})
                self._save()
                if complete:
                    self.event("study_complete", mode=self.state["mode"], floor_built=self.state["floor"]["built"])
                    seal(self.root)
                return _read(self.root / "study.json")
            except BaseException as exc:
                # A successful seal (or a partially written seal requiring
                # manual inspection) makes the tree immutable. Never invalidate
                # it by writing a later error event or checkpoint into it.
                if (self.root / "manifest.json").exists():
                    raise
                self.state["status"] = "incomplete"
                self.state["last_error_type"] = type(exc).__name__
                self._save()
                self.event("study_stopped", error_type=type(exc).__name__)
                raise
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def run_study(directory, *, phase="all", max_runtime_s=None, ledger_path=None, runner=None, planner=None):
    return StudyController(directory, max_runtime_s=max_runtime_s, ledger_path=ledger_path,
                           runner=runner, planner=planner).run(phase)
