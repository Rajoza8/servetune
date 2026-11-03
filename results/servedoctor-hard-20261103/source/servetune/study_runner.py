"""Fresh-engine study trials, bounded open-loop dispatch and sealed evidence.

This module deliberately leaves the frozen preflight request/scorer code alone.
Synthetic fixtures never instantiate an engine, GPU meter or network client.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import socket
import threading
import time
import urllib.request

from .artifacts import canonical, digest, file_hash, seal, timestamp, verify, write_json
from .deadline import SessionDeadline, TimeBudgetExceeded
from .engine import ManagedEngine, validate_engine_config
from .evidence import _function_ast, _semantic_manifest, _validate_saved_score
from .hardware import probe_hardware
from .power import PowerMeter, PowerError
from .preflight import _calibration, _load_data
from .quality import evaluate_gate, score_items, validate_dataset_manifest
from .workload import NoRedirect, completion, percentile


MAX_REQUESTS = 16384
_MAX_WORKERS = 512
_MAX_OUTSTANDING = 1024
_TUNING = ("max_num_seqs", "max_num_batched_tokens", "gpu_memory_utilization", "enable_chunked_prefill")
_DEV_START_LOCK = threading.Lock()


class StudyIdentityError(ValueError):
    pass


class DefaultsDiscoveryError(ValueError):
    pass


def verify_trial(directory):
    """Verify a trial tree without assuming that it contains preflight.json."""
    root = Path(directory)
    if root.is_symlink():
        raise ValueError("Trial root must not be a symlink")
    files = list(root.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("Trial evidence contains a symlink")
    manifest = json.loads((root / "manifest.json").read_text())
    expected = manifest.get("files")
    if manifest.get("schema_version") != 1 or not isinstance(expected, dict):
        raise ValueError("Invalid trial manifest")
    found = {p.relative_to(root).as_posix() for p in files if p.is_file() and p != root / "manifest.json"}
    if found != set(expected):
        raise ValueError("Trial evidence files were added or removed")
    for name, checksum in expected.items():
        path = root / name
        if (not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts
                or not path.resolve().is_relative_to(root.resolve())
                or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)
                or file_hash(path) != checksum):
            raise ValueError("Trial evidence hash/path mismatch")
    trial = json.loads((root / "trial.json").read_text())
    if trial.get("config_sha256") != digest(trial.get("config")):
        raise ValueError("Trial config identity mismatch")
    if trial.get("trace_sha256") != digest(json.loads((root / "trace.json").read_text())):
        raise ValueError("Trial trace identity mismatch")
    return trial


def _validate_trace(trace):
    if not isinstance(trace, dict) or not isinstance(trace.get("requests"), list):
        raise ValueError("A frozen request trace is required")
    rows = trace["requests"]
    if not 1 <= len(rows) <= MAX_REQUESTS:
        raise ValueError("Study traces require 1–16384 requests")
    previous, seen = -1.0, set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid trace row")
        arrival = row.get("arrival_s")
        if (type(arrival) not in (int, float) or not math.isfinite(arrival) or arrival < previous
                or arrival < 0 or not isinstance(row.get("id"), str) or not row["id"]
                or row["id"] in seen or not isinstance(row.get("prompt"), str) or not row["prompt"].strip()
                or type(row.get("max_output_tokens")) is not int or not 1 <= row["max_output_tokens"] <= 4096):
            raise ValueError("Invalid, unsorted or duplicate trace row")
        previous = arrival
        seen.add(row["id"])
    if rows[0]["arrival_s"] != 0:
        raise ValueError("Trace must begin at zero")
    return rows


class _DeadlineTransport:
    """Track only this trial's sockets so a deadline can interrupt request drain."""
    def __init__(self, deadline):
        self.deadline = deadline
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.sockets = set()
        self.lock = threading.Lock()
        self.closed = False

    def open(self, request, timeout):
        timeout = self.deadline.timeout(timeout)
        response = self.opener.open(request, timeout=timeout)
        try:
            sock = response.fp.raw._sock
            with self.lock:
                if self.closed:
                    raise TimeBudgetExceeded("Trial request drain was interrupted")
                self.sockets.add(sock)
        except BaseException:
            response.close()
            raise
        owner = self

        class BoundedResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                with owner.lock:
                    owner.sockets.discard(sock)
                response.close()

            def __iter__(self):
                while True:
                    sock.settimeout(owner.deadline.timeout(timeout))
                    line = response.readline()
                    if not line:
                        break
                    yield line

        return BoundedResponse()

    def abort(self):
        with self.lock:
            self.closed = True
            for sock in list(self.sockets):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


def run_study_trace(trace, request_fn, meter, *, deadline=None, event=None,
                    abort_requests=None, clock=time.monotonic, sleeper=time.sleep):
    """Dispatch arrivals centrally; worker/queue capacity never changes the trace.

    A full fixed client queue produces explicit ClientSaturation outcomes rather
    than waiting to submit and quietly lowering the offered load. Queue delay is
    included in end-to-end latency and TTFT. Raw partial outcomes survive failure.
    """
    rows = _validate_trace(trace)
    deadline = deadline or SessionDeadline()
    event = event or (lambda *args, **kwargs: None)
    outcomes, pending = {}, {}
    energy, energy_error, interrupted = None, None, None
    pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="servetune-study")
    started_meter = False
    start = clock()

    def failed(row, error):
        return {"id": row["id"], "scheduled_s": row["arrival_s"], "error": error,
                "dispatch_lag_s": None, "end_to_end_s": None}

    def serve(row):
        scheduled = start + row["arrival_s"]
        dispatched = clock()
        try:
            deadline.require()
            answer = dict(request_fn(row))
            answer.update({"id": row["id"], "scheduled_s": row["arrival_s"],
                           "dispatch_lag_s": max(0, dispatched - scheduled),
                           "end_to_end_s": max(0, clock() - scheduled),
                           "ttft_s": max(0, dispatched - scheduled) + answer["ttft_from_dispatch_s"], "error": None})
            return answer
        except Exception as exc:
            result = failed(row, type(exc).__name__)
            result.update({"dispatch_lag_s": max(0, dispatched - scheduled),
                           "end_to_end_s": max(0, clock() - scheduled)})
            return result

    def collect():
        for future in [future for future in pending if future.done()]:
            row = pending.pop(future)
            result = failed(row, "Cancelled") if future.cancelled() else future.result()
            outcomes[row["id"]] = result
            event("request_completed", id=row["id"], error=result["error"],
                  completed=len(outcomes), scheduled=len(rows))

    try:
        deadline.require()
        meter.start()
        started_meter = True
        start = clock()
        for row in rows:
            scheduled = start + row["arrival_s"]
            while clock() < scheduled:
                deadline.require()
                collect()
                sleeper(max(0, min(0.02, scheduled - clock(), deadline.remaining())))
            deadline.require()
            collect()
            if len(pending) >= _MAX_OUTSTANDING:
                outcomes[row["id"]] = failed(row, "ClientSaturation")
                event("client_saturation", id=row["id"], outstanding=len(pending))
            else:
                pending[pool.submit(serve, row)] = row
        while pending:
            deadline.require()
            wait(tuple(pending), timeout=min(0.05, deadline.remaining()), return_when=FIRST_COMPLETED)
            collect()
    except BaseException as exc:
        interrupted = type(exc).__name__
        if abort_requests is not None:
            abort_requests()
        for future in pending:
            future.cancel()
        # Owned network sockets have been shut down. A small bounded drain is
        # outside accepted measurement evidence if any worker cannot return.
        wait(tuple(pending), timeout=2)
        collect()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        if started_meter:
            try:
                energy = meter.stop()
            except BaseException as exc:
                energy_error = type(exc).__name__
                energy = {"samples": deepcopy(getattr(meter, "samples", [])), "joules": None,
                          "method": getattr(meter, "method", None), "error_type": energy_error}
    for row in rows:
        outcomes.setdefault(row["id"], failed(row, interrupted or "Incomplete"))
    ordered = [outcomes[row["id"]] for row in rows]
    good = [row for row in ordered if row["error"] is None]
    output = sum(row["usage"]["completion_tokens"] for row in good)
    prompts = sum(row["usage"]["prompt_tokens"] for row in good)
    duration = clock() - start
    joules = energy.get("joules") if energy else None
    valid_energy = type(joules) in (int, float) and math.isfinite(joules) and joules > 0
    complete = len(good) == len(rows) and interrupted is None and energy_error is None and not pending
    return {"trace_sha256": digest(trace), "measurement_window": "first scheduled arrival through final completion",
            "energy_label": "GPU energy (NVML)", "requests": ordered, "energy": energy,
            "status": "incomplete" if interrupted else "pass" if complete and valid_energy else "fail",
            "error_type": interrupted or energy_error, "all_requests_completed": complete,
            "completed_requests": len(good), "scheduled_requests": len(rows),
            "client_saturation": any(row["error"] == "ClientSaturation" for row in ordered),
            "client_policy": {"max_workers": _MAX_WORKERS, "max_outstanding": _MAX_OUTSTANDING,
                              "queue_delay_included": True, "arrival_dispatch": "main_thread_open_loop"},
            "prompt_tokens": prompts, "generated_tokens": output, "joules": joules,
            "joules_per_output_token": joules / output if valid_energy and output else None,
            "joules_per_completed_request": joules / len(good) if valid_energy and good else None,
            "output_tokens_per_second": output / duration if duration > 0 else None, "duration_s": duration,
            **{f"p{int(q * 100)}_{label}_s": percentile([row[key] for row in good], q)
               for label, key in (("latency", "end_to_end_s"), ("ttft", "ttft_s")) for q in (0.5, 0.95)}}


@contextmanager
def _owned_engine_with_introspection(engine):
    """Enable the loopback information route only in this owned child process.

    At the pinned vLLM version, /server_info is a developer route. The flag is
    inherited when ManagedEngine starts its child, then immediately restored in
    this process before any workload or quality requests are made.
    """
    with ExitStack() as owned:
        with _DEV_START_LOCK:
            previous = os.environ.get("VLLM_SERVER_DEV_MODE")
            try:
                os.environ["VLLM_SERVER_DEV_MODE"] = "1"
                entered = owned.enter_context(engine)
            finally:
                if previous is None:
                    os.environ.pop("VLLM_SERVER_DEV_MODE", None)
                else:
                    os.environ["VLLM_SERVER_DEV_MODE"] = previous
                engine.metadata["introspection"] = {
                    "source": "owned_child_VLLM_SERVER_DEV_MODE",
                    "endpoint": "/server_info?config_format=json",
                    "child_dev_mode_enabled": True,
                    "parent_dev_mode_enabled_before": previous == "1",
                    "parent_dev_mode_enabled_after": os.environ.get("VLLM_SERVER_DEV_MODE") == "1",
                    "parent_environment_restored": os.environ.get("VLLM_SERVER_DEV_MODE") == previous,
                    "measurement_included": False,
                }
        yield entered


def _effective_tuning(engine, deadline):
    """Keep only four safe scalar settings from the owned engine's server info."""
    found = {}
    try:
        url = engine.base_url.removesuffix("/v1") + "/server_info?config_format=json"
        request = urllib.request.Request(url, method="GET")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=deadline.timeout(30)) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Server info exceeds size bound")
        payload = json.loads(raw)
        value = payload.get("vllm_config", payload)
        if isinstance(value, str):
            value = json.loads(value)
        scheduler, cache = value.get("scheduler_config", {}), value.get("cache_config", {})
        for name in _TUNING[:2]:
            if type(scheduler.get(name)) is int and scheduler[name] > 0:
                found[name] = scheduler[name]
        memory = cache.get("gpu_memory_utilization")
        if type(memory) in (int, float) and math.isfinite(memory) and 0 < memory <= 1:
            found["gpu_memory_utilization"] = memory
        for name in ("enable_chunked_prefill", "chunked_prefill_enabled"):
            if type(scheduler.get(name)) is bool:
                found["enable_chunked_prefill"] = scheduler[name]
                break
    except TimeBudgetExceeded:
        raise
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    source = "owned_server_info"
    path = engine.artifact_dir / "engine.log"
    if len(found) < 4 and path.exists():
        with path.open(errors="replace") as stream:
            text = stream.read(2_000_000)
        for name in _TUNING[:2]:
            match = re.findall(r"\b" + name + r"\s*[=:]\s*(\d+)\b", text)
            if match:
                found.setdefault(name, int(match[-1]))
        match = re.findall(r"\bgpu_memory_utilization\s*[=:]\s*(0\.\d+|1\.0)\b", text)
        if match:
            found.setdefault("gpu_memory_utilization", float(match[-1]))
        if "Chunked prefill is enabled with" in text:
            found.setdefault("enable_chunked_prefill", True)
        elif "Chunked prefill is disabled" in text:
            found.setdefault("enable_chunked_prefill", False)
        source = "owned_server_info_and_explicit_startup_logs"
    if len(found) < 4:
        if engine.config["use_engine_defaults"]:
            engine.metadata["effective_tuning_values"] = found
            engine.metadata["effective_tuning_source"] = source
            raise DefaultsDiscoveryError("Engine default tuning values were not completely observed")
        found = {name: engine.config[name] for name in _TUNING}
        source = "explicit_whitelisted_command; runtime discovery incomplete"
    engine.metadata["effective_tuning_values"] = found
    engine.metadata["effective_tuning_source"] = source
    return found


class StudyRunner:
    def __init__(self, base_config, data_dir, preflight_dir, *, simulate=False):
        self.base_config = deepcopy(base_config)
        self.simulate = bool(simulate)
        self.preflight_dir = Path(preflight_dir) if preflight_dir is not None else None
        self._final_attempts = set()
        self._final_lock = threading.Lock()
        if data_dir is not None:
            self.base_config["data"] = {name: str(Path(data_dir) / f"{name}.json")
                                        for name in ("prompts", "dev", "final", "provenance")}
        if self.simulate:
            self._fp8_allowed = True
            self.hardware = {"origin": "synthetic_fixture", "gpu": {"uuid": "SIMULATED"},
                             "status": "synthetic_fixture", "vllm_version": "SIMULATED"}
            if data_dir is None:
                self.prompts = ["Synthetic performance prompt."]
                self.dev = [{"id": f"dev-{i}", "question": f"Synthetic dev {i}?", "answer": str(i)} for i in range(150)]
                self._final = [{"id": f"final-{i}", "question": f"Synthetic final {i}?", "answer": str(i)} for i in range(300)]
            else:
                self.prompts, self.dev, self._final = [json.loads(Path(self.base_config["data"][name]).read_text())
                                                        for name in ("prompts", "dev", "final")]
            validate_dataset_manifest(self.dev, self._final)
            self.baseline_score = score_items(self.dev, [{"id": row["id"], "text": f"#### {row['answer']}",
                                                          "finish_reason": "stop"} for row in self.dev])
            self.preflight_manifest_sha256 = None
            self.base_engine_config = deepcopy(self.base_config["engine"])
            return
        if self.preflight_dir is None:
            raise StudyIdentityError("Live study needs a sealed passing preflight")
        if self.preflight_dir.is_symlink() or any(path.is_symlink() for path in self.preflight_dir.rglob("*")):
            raise StudyIdentityError("Preflight evidence must not contain symlinks")
        report = verify(self.preflight_dir)
        self._fp8_allowed = report.get("checks", {}).get("P1b", {}).get("status") == "pass"
        if (report.get("mode") != "live" or not report.get("live_preflight_passed")
                or report.get("status") != "pass"
                or any(report.get("checks", {}).get(name, {}).get("status") != "pass"
                       for name in ("P1", "P2", "P4", "quality_baseline"))):
            raise StudyIdentityError("Live study needs passing real preflight gates")
        saved_config = json.loads((self.preflight_dir / "config.json").read_text())
        if report.get("config_sha256") != digest(saved_config):
            raise StudyIdentityError("Preflight config checksum differs")
        if self.base_config["engine"] != saved_config["engine"] or self.base_config["quality"] != saved_config["quality"]:
            raise StudyIdentityError("Frozen baseline engine/quality protocol differs")
        self.prompts, self.dev, data_evidence = _load_data(self.base_config)
        self._final = json.loads(Path(self.base_config["data"]["final"]).read_text())
        saved_data = json.loads((self.preflight_dir / "data-manifest.json").read_text())
        if _semantic_manifest(saved_data) != _semantic_manifest(data_evidence):
            raise StudyIdentityError("Frozen study data differ from the preflight")
        source = Path(__file__).parent
        for name in ("quality.py", "workload.py"):
            if file_hash(source / name) != file_hash(self.preflight_dir / "source" / name):
                raise StudyIdentityError("Frozen scorer/request implementation differs")
        if (_function_ast(source / "preflight.py", "_quality_baseline")
                != _function_ast(self.preflight_dir / "source" / "preflight.py", "_quality_baseline")):
            raise StudyIdentityError("Frozen quality prompt/request policy differs")
        self.baseline_score = json.loads((self.preflight_dir / "dev-baseline.json").read_text())
        _validate_saved_score(self.baseline_score, self.dev)
        self._reference_hardware = json.loads((self.preflight_dir / "hardware.json").read_text())
        self.hardware = probe_hardware(self.base_config["engine"]["gpu_index"])
        self._check_hardware(self.hardware)
        self.base_engine_config = {**deepcopy(self.base_config["engine"]), "gpu_uuid": self.hardware["gpu"]["uuid"]}
        self.preflight_manifest_sha256 = file_hash(self.preflight_dir / "manifest.json")
        baseline_meta = json.loads((self.preflight_dir / "bf16-1/engine-metadata.json").read_text())
        self._check_engine(baseline_meta, "bf16")

    def _check_hardware(self, hardware):
        if hardware.get("status") != "pass" or hardware.get("processes"):
            raise StudyIdentityError("Hardware probe failed or a foreign GPU process is present")
        reference = self._reference_hardware
        for key in ("uuid", "name", "total_memory_mib", "compute_capability"):
            if not reference.get("gpu", {}).get(key) or hardware.get("gpu", {}).get(key) != reference["gpu"][key]:
                raise StudyIdentityError("Physical GPU identity differs from the preflight")
        for key in ("driver_version", "vllm_version"):
            if not reference.get(key) or hardware.get(key) != reference[key]:
                raise StudyIdentityError("Driver or serving version differs from the preflight")

    def _check_engine(self, metadata, dtype):
        if (metadata.get("gpu_uuid") != self.hardware["gpu"]["uuid"]
                or metadata.get("vllm_version") != self.hardware["vllm_version"]
                or metadata.get("model_id") != self.base_config["engine"]["model_id"]
                or metadata.get("model_revision") != self.base_config["engine"]["model_revision"]
                or metadata.get("tokenizer_revision") != self.base_config["engine"].get("tokenizer_revision", self.base_config["engine"]["model_revision"])
                or metadata.get("dtype") != dtype or metadata.get("identity_complete") is not True):
            raise StudyIdentityError("Engine UUID/version/revision/backend identity is incomplete or differs")

    def _quality(self, engine, split, deadline, event, root):
        items = self.dev if split == "dev" else self._final
        outputs = []
        transport = _DeadlineTransport(deadline)
        with (root / f"{split}-outputs.jsonl").open("x", buffering=1) as stream:
            try:
                for item in items:
                    try:
                        # Identical prompt, greedy request and token policy to
                        # preflight._quality_baseline; only evidence streaming differs.
                        prompt = item.get("prompt", item.get("question")) + "\n\nPut your final numeric answer on its own line as #### <answer>."
                        answer = completion(engine.base_url, prompt, self.base_config["quality"]["max_output_tokens"],
                                            deadline.timeout(self.base_config["engine"]["request_timeout_s"]), opener=transport)
                        output = {"id": item["id"], "text": answer["text"],
                                  "finish_reason": answer["finish_reason"], "error": None}
                    except TimeBudgetExceeded:
                        raise
                    except Exception as exc:
                        output = {"id": item["id"], "text": "", "error": type(exc).__name__}
                    outputs.append(output)
                    stream.write(canonical(output).decode() + "\n")
                    event("quality_item_completed", split=split, completed=len(outputs), total=len(items),
                          id=item["id"], error=output["error"])
            finally:
                transport.abort()
                write_json(root / f"{split}-score.json", score_items(items, outputs))
        return score_items(items, outputs)

    def measure(self, out_dir, engine_config, dtype, trace, *, deadline=None, quality_split=None):
        rows = _validate_trace(trace)
        if quality_split not in (None, "dev", "final") or dtype not in ("bf16", "fp8"):
            raise ValueError("Use bf16/fp8 and an explicit dev/final quality split")
        config = {**self.base_engine_config, **deepcopy(engine_config)}
        if not self.simulate:
            config = validate_engine_config(config)
            frozen = set(self.base_engine_config) - set(_TUNING) - {"use_engine_defaults"}
            if any(config.get(name) != self.base_engine_config[name] for name in frozen):
                raise StudyIdentityError("Trial changed a fixed engine identity/request setting")
        identity = digest({"config": config, "dtype": dtype})
        root = Path(out_dir)
        root.mkdir(parents=True, exist_ok=False)
        deadline = deadline or SessionDeadline()
        started = time.monotonic()
        trial = {"schema_version": 1, "created_at": timestamp(), "status": "incomplete",
                 "mode": "synthetic_fixture" if self.simulate else "live", "config": config,
                 "config_sha256": digest(config), "dtype": dtype, "hardware": deepcopy(self.hardware),
                 "trace_sha256": digest(trace), "measurement": None, "quality": None, "quality_gate": None,
                 "allocated_seconds": 0, "engine_metadata": None, "record_path": str((root / "trial.json").resolve()),
                 "preflight_manifest_sha256": self.preflight_manifest_sha256, "quality_split": quality_split,
                 "calibration": None, "accepted_live_measurement": False,
                 "exclusivity_observation": "No foreign compute processes accepted in pre/post hardware probes"}
        write_json(root / "intent.json", {**trial, "claim": "Unfinished trial intent; never accepted without a sealed completed trial"})
        write_json(root / "trace.json", trace)
        write_json(root / "source-identities.json", {path.name: file_hash(path)
                   for path in sorted(Path(__file__).parent.glob("*.py"))})
        events = (root / "progress.jsonl").open("x", buffering=1)

        def event(name, **details):
            value = {"at": timestamp(), "event": name, **details}
            events.write(canonical(value).decode() + "\n")
            print(json.dumps(value, allow_nan=False), flush=True)

        engine, reraise = None, None
        try:
            if quality_split == "final":
                with self._final_lock:
                    if identity in self._final_attempts:
                        raise ValueError("This configuration already attempted its final evaluation")
                    self._final_attempts.add(identity)
            event("trial_started", mode=trial["mode"], dtype=dtype, quality_split=quality_split)
            if self.simulate:
                self._simulate(trial, trace, quality_split, event, root)
            else:
                if dtype == "fp8" and not self._fp8_allowed:
                    raise StudyIdentityError("FP8 requires a passing sealed P1b serving gate")
                hardware = probe_hardware(config["gpu_index"])
                self._check_hardware(hardware)
                write_json(root / "hardware-before.json", hardware)
                deadline.require(rows[-1]["arrival_s"] + config["request_timeout_s"] + 1)
                bounded = {**config, "startup_timeout_s": deadline.timeout(config["startup_timeout_s"])}
                engine = ManagedEngine(bounded, root / "engine", dtype)
                event("engine_starting", dtype=dtype)
                with _owned_engine_with_introspection(engine):
                    self._check_engine(engine.metadata, dtype)
                    _effective_tuning(engine, deadline)
                    warmup_transport = _DeadlineTransport(deadline)
                    try:
                        smoke = completion(engine.base_url, "Reply with the single word ready.", 2048,
                                           deadline.timeout(config["request_timeout_s"]),
                                           opener=warmup_transport, temperature=1)
                        write_json(root / "smoke.json", smoke)
                        if not smoke["text"].strip() or smoke["finish_reason"] != "stop":
                            raise ValueError("Owned engine smoke did not complete")
                        for _ in range(self.base_config["measurement"]["warmup_requests"]):
                            completion(engine.base_url, self.prompts[0], rows[0]["max_output_tokens"],
                                       deadline.timeout(config["request_timeout_s"]), opener=warmup_transport)
                    finally:
                        warmup_transport.abort()
                    event("measurement_started", requests=len(rows))
                    transport = _DeadlineTransport(deadline)
                    try:
                        measurement = run_study_trace(trace,
                            lambda row: completion(engine.base_url, row["prompt"], row["max_output_tokens"],
                                                   deadline.timeout(config["request_timeout_s"]), opener=transport),
                            PowerMeter(config["gpu_index"], gpu_uuid=self.hardware["gpu"]["uuid"]),
                            deadline=deadline, event=event, abort_requests=transport.abort)
                    finally:
                        transport.abort()
                    trial["measurement"] = measurement
                    write_json(root / "measurement.json", measurement)
                    event("measurement_completed", status=measurement["status"], completed=measurement["completed_requests"])
                    if measurement["status"] != "pass":
                        if measurement["status"] == "incomplete":
                            if measurement.get("error_type") == "KeyboardInterrupt":
                                raise KeyboardInterrupt()
                            if measurement.get("error_type") == "SystemExit":
                                raise SystemExit()
                            raise TimeBudgetExceeded("Trace was interrupted")
                        raise ValueError("Trace failed or the fixed client dispatcher saturated")
                    if measurement["energy"].get("gpu_uuid") != self.hardware["gpu"]["uuid"]:
                        raise PowerError("Measured GPU UUID differs")
                    trial["calibration"] = _calibration(measurement["energy"])
                    if not trial["calibration"]["pass"]:
                        raise PowerError("Complete-workload counter boundary bound is not below 1%")
                    if quality_split is not None:
                        trial["quality"] = self._quality(engine, quality_split, deadline, event, root)
                        if quality_split == "dev":
                            trial["quality_gate"] = evaluate_gate(trial["quality"], self.baseline_score, "dev")
                if engine.metadata.get("cleanup_status") != "completed":
                    raise StudyIdentityError("Owned engine cleanup was not completed")
                after = probe_hardware(config["gpu_index"])
                self._check_hardware(after)
                write_json(root / "hardware-after.json", after)
                trial["status"] = "pass" if not trial["quality_gate"] or trial["quality_gate"]["passed"] else "fail"
                if trial["quality"] and trial["quality"]["failed_requests"]:
                    trial["status"] = "fail"
                trial["accepted_live_measurement"] = trial["status"] == "pass"
        except BaseException as exc:
            trial["status"] = "incomplete" if isinstance(exc, (TimeBudgetExceeded, KeyboardInterrupt, SystemExit)) else "fail"
            trial["error_type"] = type(exc).__name__
            event("trial_interrupted" if trial["status"] == "incomplete" else "trial_failed", error_type=type(exc).__name__)
            if not isinstance(exc, Exception):
                reraise = exc
        finally:
            if engine is not None:
                trial["engine_metadata"] = deepcopy(engine.metadata)
                write_json(root / "engine-metadata.json", trial["engine_metadata"])
            trial["allocated_seconds"] = time.monotonic() - started
            trial["finished_at"] = timestamp()
            event("trial_finished", status=trial["status"], allocated_seconds=trial["allocated_seconds"])
            events.close()
            write_json(root / "trial.json", trial)
            seal(root)
        if reraise is not None:
            raise reraise
        return trial

    def _simulate(self, trial, trace, quality_split, event, root):
        rows = trace["requests"]
        factor = 1 + (int(digest({"config": trial["config"], "dtype": trial["dtype"]})[:8], 16) % 50) / 100
        duration = max(1, rows[-1]["arrival_s"] + 0.2)
        outcomes = [{"id": row["id"], "scheduled_s": row["arrival_s"], "error": None,
                     "text": "SYNTHETIC FIXTURE", "finish_reason": "stop", "dispatch_lag_s": 0,
                     "ttft_s": .02 * factor, "end_to_end_s": .2 * factor,
                     "usage": {"prompt_tokens": 16, "completion_tokens": row["max_output_tokens"]}}
                    for row in rows]
        output = sum(row["max_output_tokens"] for row in rows)
        joules = output * factor
        trial["measurement"] = {"origin": "synthetic_fixture", "status": "synthetic_fixture",
            "trace_sha256": digest(trace), "requests": outcomes, "energy": {"origin": "synthetic_fixture", "joules": joules},
            "all_requests_completed": True, "completed_requests": len(rows), "scheduled_requests": len(rows),
            "generated_tokens": output, "prompt_tokens": len(rows) * 16, "duration_s": duration,
            "joules": joules, "joules_per_output_token": factor, "joules_per_completed_request": joules / len(rows),
            "output_tokens_per_second": output / duration, "p95_latency_s": .2 * factor, "p50_latency_s": .2 * factor,
            "p95_ttft_s": .02 * factor, "p50_ttft_s": .02 * factor}
        write_json(root / "measurement.json", trial["measurement"])
        if quality_split:
            items = self.dev if quality_split == "dev" else self._final
            outputs = [{"id": row["id"], "text": f"#### {row['answer']}", "finish_reason": "stop"} for row in items]
            write_json(root / f"{quality_split}-outputs.json", outputs)
            trial["quality"] = score_items(items, outputs)
            write_json(root / f"{quality_split}-score.json", trial["quality"])
            if quality_split == "dev":
                trial["quality_gate"] = evaluate_gate(trial["quality"], self.baseline_score, "dev")
        trial["status"] = "synthetic_fixture"
        trial["calibration"] = {"pass": False, "reason": "Synthetic fixtures cannot calibrate real GPU energy"}
        event("synthetic_trial_completed", requests=len(rows), live_measurement=False)
