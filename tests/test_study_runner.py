from copy import deepcopy
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
from socketserver import TCPServer
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from servetune.artifacts import digest, file_hash, seal, write_json
from servetune.config import DEFAULT
from servetune.deadline import SessionDeadline, TimeBudgetExceeded
from servetune.engine import EngineError
from servetune.quality import score_items, validate_dataset_manifest
from servetune.study_runner import (DefaultsDiscoveryError, StudyIdentityError, StudyRunner,
                                    _DeadlineTransport, _effective_tuning, _owned_engine_with_introspection,
                                    run_study_trace, verify_trial)
from servetune.workload import completion


HARDWARE = {"status": "pass", "gpu": {"uuid": "GPU-study", "name": "RTX PRO 6000 Blackwell",
            "total_memory_mib": 97887.0, "compute_capability": "12.0"},
            "driver_version": "615.71.09", "vllm_version": "pinned-study", "processes": []}


def trace(count=2, interval=.005):
    return {"requests": [{"id": f"r{i}", "arrival_s": i * interval,
                           "prompt": "Performance prompt", "max_output_tokens": 8} for i in range(count)]}


def answer(*args, **kwargs):
    return {"text": "ready", "finish_reason": "stop", "usage": {"prompt_tokens": 8, "completion_tokens": 8},
            "ttft_from_dispatch_s": .001, "elapsed_from_dispatch_s": .002}


class Meter:
    method = "nvml_total_energy_counter"

    def __init__(self, *args, **kwargs):
        self.started = self.stopped = False
        self.samples = [{"monotonic_s": i / 10, "energy_mj": i * 1000, "gpu_uuid": "GPU-study"}
                        for i in range(1001)]

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        return {"joules": 1000, "duration_s": 100, "method": self.method,
                "gpu_uuid": "GPU-study", "samples": self.samples}


class Engine:
    fail_cleanup = False
    instances = []

    def __init__(self, config, artifact_dir, dtype):
        self.config, self.artifact_dir, self.dtype = config, Path(artifact_dir), dtype
        self.base_url = "http://127.0.0.1:8000/v1"
        self.metadata = {"dtype": dtype, "model_id": config["model_id"],
                         "model_revision": config["model_revision"], "tokenizer_revision": config["model_revision"],
                         "gpu_uuid": "GPU-study", "vllm_version": "pinned-study", "identity_complete": True,
                         "kernel_backend_lines": ["Selected fixture backend"], "memory_footprint_lines": ["Model loading took 55 GiB"]}
        self.instances.append(self)

    def __enter__(self):
        self.artifact_dir.mkdir()
        (self.artifact_dir / "engine.log").write_text("Owned fixture engine\n")
        return self

    def __exit__(self, *args):
        self.metadata["cleanup_status"] = "failed" if self.fail_cleanup else "completed"
        if self.fail_cleanup:
            raise EngineError("fixture cleanup failure")


def fixture(root):
    data = root / "data"
    data.mkdir()
    config = deepcopy(DEFAULT)
    config["engine"]["model_revision"] = "a" * 40
    config["data"] = {name: str(data / f"{name}.json") for name in ("prompts", "dev", "final", "provenance")}
    dev = [{"id": f"dev-{i}", "question": f"Dev question {i}?", "answer": str(i)} for i in range(150)]
    final = [{"id": f"final-{i}", "question": f"Final question {i}?", "answer": str(i)} for i in range(300)]
    for name, value in (("prompts", ["Public performance question"]), ("dev", dev), ("final", final)):
        write_json(data / f"{name}.json", value)
    provenance = {"origin": "public_fixture_for_unit_test", "license": "CC0",
                  "quality_manifest": validate_dataset_manifest(dev, final),
                  "files_sha256": {f"{name}.json": file_hash(data / f"{name}.json") for name in ("prompts", "dev", "final")}}
    write_json(data / "provenance.json", provenance)
    preflight = root / "preflight"
    preflight.mkdir()
    write_json(preflight / "config.json", config)
    write_json(preflight / "hardware.json", HARDWARE)
    write_json(preflight / "dev-baseline.json", score_items(dev, [{"id": r["id"], "text": f"#### {r['answer']}",
                                                                  "finish_reason": "stop"} for r in dev]))
    write_json(preflight / "data-manifest.json", {"split_validation": validate_dataset_manifest(dev, final),
        "files": {name: {"path": config["data"][name], "sha256": file_hash(config["data"][name])} for name in config["data"]},
        "provenance": provenance})
    source = preflight / "source"
    source.mkdir()
    import servetune.preflight as module
    for name in ("quality.py", "workload.py", "preflight.py"):
        shutil.copyfile(Path(module.__file__).parent / name, source / name)
    write_json(preflight / "bf16-1/engine-metadata.json", {
        "dtype": "bf16", "model_id": config["engine"]["model_id"], "model_revision": "a" * 40,
        "tokenizer_revision": "a" * 40, "gpu_uuid": "GPU-study", "vllm_version": "pinned-study", "identity_complete": True})
    write_json(preflight / "preflight.json", {"mode": "live", "status": "pass", "live_preflight_passed": True,
        "config_sha256": digest(config), "checks": {name: {"status": "pass"} for name in ("P1", "P1b", "P2", "P4", "quality_baseline")}})
    seal(preflight)
    return config, data, preflight


class SchedulerTests(unittest.TestCase):
    def test_central_dispatch_does_not_wait_for_prior_completion(self):
        observed = []

        def request(row):
            observed.append((row["id"], time.monotonic()))
            if row["id"] == "r0":
                time.sleep(.07)
            return answer()

        meter = Meter()
        result = run_study_trace(trace(2, .01), request, meter)
        self.assertEqual(result["status"], "pass")
        self.assertLess(observed[1][1] - observed[0][1], .05)
        self.assertTrue(meter.stopped)

    def test_queue_delay_is_in_latency_and_saturation_is_explicit(self):
        gate = threading.Event()
        release = threading.Timer(.05, gate.set)
        release.start()
        try:
            with patch("servetune.study_runner._MAX_WORKERS", 1), patch("servetune.study_runner._MAX_OUTSTANDING", 2):
                result = run_study_trace(trace(3, 0), lambda row: (gate.wait(1), answer())[1], Meter())
        finally:
            gate.set()
            release.join()
        self.assertEqual(result["status"], "fail")
        self.assertTrue(result["client_saturation"])
        self.assertEqual(result["requests"][2]["error"], "ClientSaturation")
        self.assertGreater(result["requests"][1]["dispatch_lag_s"], .02)
        self.assertGreater(result["requests"][1]["ttft_s"], .02)

    def test_more_than_256_requests_without_one_sleeping_worker_per_row(self):
        with patch("servetune.study_runner._MAX_WORKERS", 2):
            result = run_study_trace(trace(300, 0), lambda row: answer(), Meter())
        self.assertEqual(result["completed_requests"], 300)
        self.assertEqual(result["client_policy"]["max_workers"], 2)

    def test_deadline_aborts_own_requests_stops_meter_and_retains_outcomes(self):
        class Deadline:
            calls = 0

            def require(self, *args):
                self.calls += 1
                if self.calls > 2:
                    raise TimeBudgetExceeded()
                return 1

            def remaining(self):
                return 1

        abort = threading.Event()
        meter = Meter()
        result = run_study_trace(trace(3, .01), lambda row: answer(), meter, deadline=Deadline(), abort_requests=abort.set)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(len(result["requests"]), 3)
        self.assertTrue(meter.stopped)
        self.assertTrue(abort.is_set())


class DefaultsTests(unittest.TestCase):
    def test_safe_runtime_fields_only(self):
        payload = {"vllm_config": {"scheduler_config": {"max_num_seqs": 1024, "max_num_batched_tokens": 8192,
                    "enable_chunked_prefill": True}, "cache_config": {"gpu_memory_utilization": .92}},
                   "vllm_env": {"SECRET": "do not retain"}, "system_env": "do not retain"}
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine({**DEFAULT["engine"], "model_revision": "a" * 40}, Path(directory), "bf16")
            response = io.BytesIO(json.dumps(payload).encode())
            with patch("servetune.study_runner.urllib.request.build_opener") as opener:
                opener.return_value.open.return_value.__enter__.return_value = response
                values = _effective_tuning(engine, SessionDeadline())
                self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 30)
            self.assertEqual(values, {"max_num_seqs": 1024, "max_num_batched_tokens": 8192,
                                      "enable_chunked_prefill": True, "gpu_memory_utilization": .92})
            self.assertNotIn("do not retain", json.dumps(engine.metadata))

    def test_info_timeout_cannot_exceed_session_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine({**DEFAULT["engine"], "model_revision": "a" * 40}, Path(directory), "bf16")
            with patch("servetune.study_runner.urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = OSError()
                with self.assertRaises(DefaultsDiscoveryError):
                    _effective_tuning(engine, SessionDeadline(35))
                timeout = opener.return_value.open.call_args.kwargs["timeout"]
                self.assertGreater(timeout, 0)
                self.assertLessEqual(timeout, 5)

    def test_dev_route_enabled_only_for_owned_start_then_parent_restored(self):
        observations = []

        class Owned:
            metadata = {}
            def __enter__(self):
                observations.append(("start", os.environ.get("VLLM_SERVER_DEV_MODE")))
                return self
            def __exit__(self, *args):
                observations.append(("cleanup", os.environ.get("VLLM_SERVER_DEV_MODE")))

        for initial in (None, "0", "1"):
            with self.subTest(initial=initial), patch.dict(os.environ):
                if initial is None:
                    os.environ.pop("VLLM_SERVER_DEV_MODE", None)
                else:
                    os.environ["VLLM_SERVER_DEV_MODE"] = initial
                owned = Owned()
                with _owned_engine_with_introspection(owned):
                    self.assertEqual(os.environ.get("VLLM_SERVER_DEV_MODE"), initial)
                    self.assertTrue(owned.metadata["introspection"]["parent_environment_restored"])
                self.assertEqual(observations[-2:], [("start", "1"), ("cleanup", initial)])

    def test_dev_flag_restored_after_owned_start_failure(self):
        class Broken:
            metadata = {}
            def __enter__(self):
                self.assertion = os.environ.get("VLLM_SERVER_DEV_MODE")
                raise EngineError("owned startup failure")
            def __exit__(self, *args):
                raise AssertionError("Failed context entry cannot enter cleanup twice")

        with patch.dict(os.environ, {"VLLM_SERVER_DEV_MODE": "0"}):
            owned = Broken()
            with self.assertRaises(EngineError), _owned_engine_with_introspection(owned):
                pass
            self.assertEqual(owned.assertion, "1")
            self.assertEqual(os.environ["VLLM_SERVER_DEV_MODE"], "0")
            self.assertTrue(owned.metadata["introspection"]["parent_environment_restored"])

    def test_partial_defaults_block_instead_of_inventing(self):
        from servetune.deadline import SessionDeadline
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine({**DEFAULT["engine"], "model_revision": "a" * 40}, Path(directory), "bf16")
            (Path(directory) / "engine.log").write_text("Chunked prefill is enabled with max_num_batched_tokens=8192\n")
            with patch("servetune.study_runner.urllib.request.build_opener", side_effect=OSError):
                with self.assertRaises(DefaultsDiscoveryError):
                    _effective_tuning(engine, SessionDeadline())
            self.assertEqual(engine.metadata["effective_tuning_values"], {"max_num_batched_tokens": 8192, "enable_chunked_prefill": True})

    def test_explicit_command_fallback_is_identified_as_requested(self):
        from servetune.deadline import SessionDeadline
        with tempfile.TemporaryDirectory() as directory:
            config = {**DEFAULT["engine"], "model_revision": "a" * 40, "use_engine_defaults": False}
            engine = Engine(config, Path(directory), "bf16")
            with patch("servetune.study_runner.urllib.request.build_opener", side_effect=OSError):
                result = _effective_tuning(engine, SessionDeadline())
            self.assertEqual(result["max_num_seqs"], config["max_num_seqs"])
            self.assertIn("explicit_whitelisted_command", engine.metadata["effective_tuning_source"])


class DeadlineTransportTests(unittest.TestCase):
    @contextmanager
    def owned_loopback_sse(self, *, stall=False):
        release, connected = threading.Event(), threading.Event()
        received = []
        events = [
            {"choices": [{"delta": {"content": "ready"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1}},
        ]
        payload = b"".join(b"data: " + json.dumps(row).encode() + b"\n\n" for row in events) + b"data: [DONE]\n\n"

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if stall:
                    self.wfile.write(b"data: " + json.dumps(events[0]).encode() + b"\n\n")
                    self.wfile.flush()
                    connected.set()
                    release.wait(5)
                    return
                self.wfile.write(payload)
                self.wfile.flush()
                connected.set()

        class LoopbackServer(ThreadingHTTPServer):
            def server_bind(self):
                # Avoid HTTPServer's reverse DNS lookup: this test is local only.
                TCPServer.server_bind(self)
                self.server_name, self.server_port = "localhost", self.server_address[1]

        server = LoopbackServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", received, connected
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_real_urllib_sse_socket_path_and_cleanup(self):
        transport = _DeadlineTransport(SessionDeadline(40))
        with self.owned_loopback_sse() as (url, received, connected):
            result = completion(url, "Local test prompt", 8, 2, opener=transport)
        self.assertEqual(result["text"], "ready")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["usage"], {"prompt_tokens": 2, "completion_tokens": 1})
        self.assertEqual(received[0][0], "/v1/chat/completions")
        self.assertTrue(received[0][1]["stream"])
        self.assertEqual(transport.sockets, set())

    def test_abort_interrupts_only_owned_stalled_stream(self):
        transport = _DeadlineTransport(SessionDeadline(40))
        errors = []
        with self.owned_loopback_sse(stall=True) as (url, received, connected):
            def request():
                try:
                    completion(url, "Local test prompt", 8, 5, opener=transport)
                except Exception as exc:
                    errors.append(type(exc).__name__)

            worker = threading.Thread(target=request, daemon=True)
            worker.start()
            self.assertTrue(connected.wait(2))
            for _ in range(100):
                with transport.lock:
                    registered = bool(transport.sockets)
                if registered:
                    break
                time.sleep(.005)
            self.assertTrue(registered)
            transport.abort()
            worker.join(2)
            self.assertFalse(worker.is_alive(), "Owned stream must stop before its request timeout")
        self.assertEqual(len(errors), 1)
        self.assertTrue(transport.closed)
        self.assertEqual(transport.sockets, set())


class RunnerTests(unittest.TestCase):
    def setUp(self):
        Engine.fail_cleanup = False
        Engine.instances.clear()

    def test_simulation_has_no_hardware_engine_meter_or_network_and_final_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory, patch("servetune.study_runner.probe_hardware") as probe, \
             patch("servetune.study_runner.ManagedEngine") as engine, patch("servetune.study_runner.PowerMeter") as meter, \
             patch("servetune.study_runner.completion") as complete, patch("sys.stdout", new_callable=io.StringIO):
            root = Path(directory)
            runner = StudyRunner(deepcopy(DEFAULT), None, None, simulate=True)
            result = runner.measure(root / "one", runner.base_engine_config, "bf16", trace())
            self.assertEqual(result["mode"], "synthetic_fixture")
            self.assertIsNone(result["quality"])
            self.assertFalse(result["accepted_live_measurement"])
            final = runner.measure(root / "two", runner.base_engine_config, "bf16", trace(), quality_split="final")
            self.assertEqual(final["quality"]["items"], 300)
            self.assertIsNone(final["quality_gate"])
            again = runner.measure(root / "three", runner.base_engine_config, "bf16", trace(), quality_split="final")
            self.assertEqual(again["status"], "fail")
            verify_trial(root / "two")
            for mocked in (probe, engine, meter, complete):
                mocked.assert_not_called()

    def test_live_requires_seal_and_exact_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            config, data, preflight = fixture(Path(directory))
            changed = deepcopy(HARDWARE)
            changed["gpu"]["uuid"] = "GPU-other"
            with patch("servetune.study_runner.probe_hardware", return_value=changed):
                with self.assertRaises(StudyIdentityError):
                    StudyRunner(config, data, preflight)
            (preflight / "hardware.json").write_text("{}")
            with self.assertRaises(ValueError):
                StudyRunner(config, data, preflight)

    def test_live_trial_sealed_and_cleanup_failure_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdout", new_callable=io.StringIO):
            root = Path(directory)
            config, data, preflight = fixture(root)
            with patch("servetune.study_runner.probe_hardware", return_value=deepcopy(HARDWARE)), \
                 patch("servetune.study_runner.ManagedEngine", Engine), patch("servetune.study_runner.PowerMeter", Meter), \
                 patch("servetune.study_runner.completion", side_effect=answer), patch("servetune.study_runner._effective_tuning", return_value={}):
                runner = StudyRunner(config, data, preflight)
                passed = runner.measure(root / "good", runner.base_engine_config, "bf16", trace())
                self.assertEqual(passed["status"], "pass")
                self.assertTrue(passed["calibration"]["pass"])
                self.assertEqual(verify_trial(root / "good"), passed)
                Engine.fail_cleanup = True
                failed = runner.measure(root / "bad", runner.base_engine_config, "bf16", trace())
                self.assertEqual(failed["status"], "fail")
                self.assertEqual(failed["engine_metadata"]["cleanup_status"], "failed")
                self.assertFalse(failed["accepted_live_measurement"])
                verify_trial(root / "bad")
                (root / "good/measurement.json").write_text("{}")
                with self.assertRaises(ValueError):
                    verify_trial(root / "good")

    def test_quality_uses_frozen_prompt_and_greedy_policy_and_full_dev(self):
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdout", new_callable=io.StringIO):
            root = Path(directory)
            config, data, preflight = fixture(root)
            calls = []

            def complete(url, prompt, cap, timeout, **kwargs):
                calls.append((prompt, cap, kwargs))
                result = answer()
                if prompt.startswith("Dev question"):
                    result["text"] = "#### " + prompt.split("?")[0].rsplit(" ", 1)[1]
                return result

            with patch("servetune.study_runner.probe_hardware", return_value=deepcopy(HARDWARE)), \
                 patch("servetune.study_runner.ManagedEngine", Engine), patch("servetune.study_runner.PowerMeter", Meter), \
                 patch("servetune.study_runner.completion", side_effect=complete), patch("servetune.study_runner._effective_tuning", return_value={}):
                runner = StudyRunner(config, data, preflight)
                result = runner.measure(root / "trial", runner.base_engine_config, "bf16", trace(), quality_split="dev")
            dev_calls = [row for row in calls if row[0].startswith("Dev question")]
            self.assertEqual(len(dev_calls), 150)
            self.assertEqual(dev_calls[0][0], "Dev question 0?\n\nPut your final numeric answer on its own line as #### <answer>.")
            self.assertEqual(dev_calls[0][1], config["quality"]["max_output_tokens"])
            self.assertNotIn("temperature", dev_calls[0][2])
            self.assertEqual(result["quality"]["correct"], 150)
            self.assertTrue(result["quality_gate"]["passed"])
            self.assertFalse(any(prompt.startswith("Final question") for prompt, _, _ in calls))
            self.assertEqual(len((root / "trial/dev-outputs.jsonl").read_text().splitlines()), 150)

    def test_foreign_process_appearing_after_init_blocks_trial(self):
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdout", new_callable=io.StringIO):
            root = Path(directory)
            config, data, preflight = fixture(root)
            occupied = {**deepcopy(HARDWARE), "processes": [{"pid": 123}]}
            with patch("servetune.study_runner.probe_hardware", side_effect=[deepcopy(HARDWARE), occupied]), \
                 patch("servetune.study_runner.ManagedEngine") as engine:
                runner = StudyRunner(config, data, preflight)
                result = runner.measure(root / "trial", runner.base_engine_config, "bf16", trace())
                self.assertEqual(result["error_type"], "StudyIdentityError")
                engine.assert_not_called()

    def test_final_uses_full_300_items_and_never_compares_to_dev_reference(self):
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdout", new_callable=io.StringIO):
            root = Path(directory)
            config, data, preflight = fixture(root)
            count = 0

            def complete(url, prompt, *args, **kwargs):
                nonlocal count
                result = answer()
                if prompt.startswith("Final question"):
                    count += 1
                    result["text"] = "#### " + prompt.split("?")[0].rsplit(" ", 1)[1]
                return result

            with patch("servetune.study_runner.probe_hardware", return_value=deepcopy(HARDWARE)), \
                 patch("servetune.study_runner.ManagedEngine", Engine), patch("servetune.study_runner.PowerMeter", Meter), \
                 patch("servetune.study_runner.completion", side_effect=complete), patch("servetune.study_runner._effective_tuning", return_value={}):
                runner = StudyRunner(config, data, preflight)
                result = runner.measure(root / "final", runner.base_engine_config, "bf16", trace(), quality_split="final")
                repeated = runner.measure(root / "duplicate", runner.base_engine_config, "bf16", trace(), quality_split="final")
            self.assertEqual(count, 300)
            self.assertEqual(result["quality"]["items"], 300)
            self.assertEqual(result["quality"]["correct"], 300)
            self.assertIsNone(result["quality_gate"])
            self.assertEqual(repeated["status"], "fail")
            self.assertEqual(len((root / "final/final-outputs.jsonl").read_text().splitlines()), 300)


if __name__ == "__main__":
    unittest.main()
