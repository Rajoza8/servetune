"""Offline collector failures must remain failed recordings with safe evidence."""
import errno
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from servetune.artifacts import file_hash
from servedoctor.live import run_live
from servedoctor.loadgen import Gateway, LoadGenerator, LoadGeneratorError
from servedoctor.observe import load_incident
from servedoctor.record import record_incident, record_study
from servedoctor.telemetry import LogTail, Recorder, RecorderError, read_jsonl

PRIVATE = "injected-private-exception-detail"


class CollectorFailureTests(unittest.TestCase):
    def test_real_recorder_thread_failure_is_safe_and_preserves_partial_rows(self):
        failed = threading.Event()

        class Tail:
            calls = 0

            def read(self):
                self.calls += 1
                if self.calls == 2:
                    failed.set()
                    raise OSError(errno.EMFILE, PRIVATE)
                return []

        with tempfile.TemporaryDirectory() as td, patch("threading.excepthook") as hook:
            path = Path(td) / "telemetry.jsonl"
            recorder = Recorder(path, clock_zero=time.monotonic(), log_tail=Tail(), interval_s=.001)
            recorder.start()
            self.assertTrue(failed.wait(2))
            with self.assertRaises(RecorderError) as caught:
                recorder.stop()
            self.assertEqual(caught.exception.failures, ["OSError"])
            self.assertFalse(caught.exception.thread_alive)
            self.assertNotIn(PRIVATE, str(caught.exception))
            self.assertEqual(len(read_jsonl(path)), 1)
            self.assertEqual(recorder.rows, 1)
            hook.assert_not_called()

    def test_bounded_stop_reports_a_thread_that_has_not_stopped(self):
        entered, release = threading.Event(), threading.Event()

        class Tail:
            def read(self):
                entered.set()
                release.wait(2)
                return []

        with tempfile.TemporaryDirectory() as td:
            recorder = Recorder(Path(td) / "telemetry.jsonl", clock_zero=time.monotonic(), log_tail=Tail())
            try:
                recorder.start()
                self.assertTrue(entered.wait(2))
                with self.assertRaises(RecorderError) as caught:
                    recorder.stop(timeout_s=.001)
                self.assertTrue(caught.exception.thread_alive)
                self.assertEqual(caught.exception.failures, [])
            finally:
                release.set()
                recorder.stop()

    def test_successful_recorder_keeps_snapshot_format(self):
        sampled = threading.Event()

        def config():
            sampled.set()
            return {"max_num_seqs": 64}

        with tempfile.TemporaryDirectory() as td:
            recorder = Recorder(Path(td) / "telemetry.jsonl", clock_zero=time.monotonic(), config_fn=config)
            recorder.start()
            self.assertTrue(sampled.wait(2))
            recorder.stop()
            rows = read_jsonl(recorder.out_path)
            self.assertEqual(set(rows[0]), {"t", "engine_config"})
            self.assertEqual(rows[0]["engine_config"], {"max_num_seqs": 64})
            self.assertEqual(recorder.failures, [])

    def test_background_close_failure_is_reported_without_source_message(self):
        sampled = threading.Event()

        class BrokenClose(io.StringIO):
            def close(self):
                super().close()
                raise OSError(PRIVATE)

        stream = BrokenClose()
        with tempfile.TemporaryDirectory() as td, patch.object(Path, "open", return_value=stream), \
                patch("threading.excepthook") as hook:
            recorder = Recorder(Path(td) / "telemetry.jsonl", clock_zero=time.monotonic(),
                                config_fn=lambda: sampled.set() or {})
            recorder.start()
            self.assertTrue(sampled.wait(2))
            with self.assertRaises(RecorderError) as caught:
                recorder.stop()
            self.assertEqual(caught.exception.failures, ["OSError"])
            self.assertNotIn(PRIVATE, str(caught.exception))
            self.assertTrue(stream.closed)
            hook.assert_not_called()

    def test_thread_start_failure_closes_stream_and_preserves_original(self):
        stream = io.StringIO()
        primary = RuntimeError(PRIVATE)
        with tempfile.TemporaryDirectory() as td, patch.object(Path, "open", return_value=stream), \
                patch.object(threading.Thread, "start", side_effect=primary):
            recorder = Recorder(Path(td) / "telemetry.jsonl", clock_zero=time.monotonic())
            with self.assertRaises(RuntimeError) as caught:
                recorder.start()
            self.assertIs(caught.exception, primary)
            self.assertTrue(stream.closed)
            recorder.stop()

    def scenario(self):
        return {"id": "inc-stub", "duration_s": .02, "engine": {}, "events": [],
                "slo": {"p95_latency_s": 10, "max_error_rate": .01}, "request_timeout_s": 1}

    def engine(self, root):
        engine = Mock(metadata={}, base_url="http://127.0.0.1:9/v1", artifact_dir=root / "engine")
        engine.artifact_dir.mkdir()
        (engine.artifact_dir / "engine.log").write_text("", encoding="utf-8")
        return engine

    def check_failed(self, root, failure):
        incident = root / "incidents" / "inc-stub"
        recording = json.loads((incident / "recording.json").read_text())
        self.assertEqual(recording["status"], "failed")
        self.assertEqual(recording["failure"], failure)
        self.assertTrue((incident / "requests.jsonl").exists())
        manifest = json.loads((incident / "manifest.json").read_text())
        self.assertEqual(set(manifest["files"]), {p.name for p in incident.iterdir()
                                                if p.name != "manifest.json"})
        for name, sha in manifest["files"].items():
            self.assertEqual(file_hash(incident / name), sha)
        self.assertNotIn(PRIVATE, (incident / "recording.json").read_text())
        with self.assertRaises(ValueError):
            load_incident(incident)
        return recording

    def test_logtail_emfile_thread_failure_seals_failed_recording(self):
        failed = threading.Event()

        def read(_):
            failed.set()
            raise OSError(errno.EMFILE, PRIVATE)

        def sleep(_):
            self.assertTrue(failed.wait(2))

        def recorder(*args, **kwargs):
            return Recorder(*args, **kwargs, scrape=lambda _: {})

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("servedoctor.record.make_arrivals", return_value=[]), \
                    patch("servedoctor.record.Recorder", side_effect=recorder), \
                    patch.object(LogTail, "read", read):
                with self.assertRaises(RecorderError):
                    record_incident(self.scenario(), engine=self.engine(root), pools={}, out_dir=root, sleeper=sleep)
            saved = self.check_failed(root, "RecorderError")
            self.assertEqual(saved["failure_stage"], "cleanup")
            self.assertEqual(saved["background_errors"], ["OSError"])
            self.assertEqual(saved["cleanup_errors"], [{"resource": "recorder", "error": "RecorderError",
                                                     "background_errors": ["OSError"], "thread_alive": False}])

    def test_late_collector_release_cannot_mutate_a_sealed_recording(self):
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt), tempfile.TemporaryDirectory() as td:
                entered, release = threading.Event(), threading.Event()
                recorders = []
                primary = KeyboardInterrupt(PRIVATE)

                def read(_):
                    entered.set()
                    release.wait(2)
                    return []

                def sleeper(_):
                    self.assertTrue(entered.wait(2))
                    if interrupt:
                        raise primary

                def recorder(*args, **kwargs):
                    item = Recorder(*args, **kwargs, scrape=lambda _: {})
                    item.stop = lambda: Recorder.stop(item, timeout_s=.001)
                    recorders.append(item)
                    return item

                root = Path(td)
                try:
                    with patch("servedoctor.record.make_arrivals", return_value=[]), \
                            patch("servedoctor.record.Recorder", side_effect=recorder), \
                            patch.object(LogTail, "read", read):
                        with self.assertRaises(KeyboardInterrupt if interrupt else RecorderError) as caught:
                            record_incident(self.scenario(), engine=self.engine(root), pools={},
                                            out_dir=root, sleeper=sleeper)
                    if interrupt:
                        self.assertIs(caught.exception, primary)
                    incident = root / "incidents/inc-stub"
                    saved = json.loads((incident / "recording.json").read_text())
                    self.assertEqual(saved["status"], "failed")
                    self.assertEqual(saved["seal_state"], "unsealed_collector_alive")
                    self.assertTrue(saved["telemetry_may_still_change"])
                    self.assertFalse((incident / "manifest.json").exists())
                    immutable = {p.name: file_hash(p) for p in incident.iterdir() if p.name != "telemetry.jsonl"}
                    telemetry_before = (incident / "telemetry.jsonl").read_bytes()
                    with self.assertRaises(ValueError):
                        load_incident(incident)
                finally:
                    release.set()
                    for item in recorders:
                        Recorder.stop(item)
                self.assertNotEqual((incident / "telemetry.jsonl").read_bytes(), telemetry_before)
                self.assertFalse((incident / "manifest.json").exists())
                self.assertEqual({p.name: file_hash(p) for p in incident.iterdir()
                                  if p.name != "telemetry.jsonl"}, immutable)
                self.assertNotIn(PRIVATE, (incident / "recording.json").read_text())

    def test_live_caller_retains_failed_unsealed_evidence_after_late_release(self):
        entered, release = threading.Event(), threading.Event()
        recorders = []

        def read(_):
            entered.set()
            release.wait(2)
            return []

        def recorder(*args, **kwargs):
            kwargs["scrape"] = lambda _: {}
            item = Recorder(*args, **kwargs)
            item.stop = lambda: Recorder.stop(item, timeout_s=.001)
            recorders.append(item)
            return item

        def factory(_, path, dtype):
            path.mkdir(parents=True)
            return Mock(metadata={}, artifact_dir=path, base_url="http://127.0.0.1:9/v1")

        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "live"
            try:
                with patch("servedoctor.live.make_arrivals", return_value=[]), \
                        patch("servedoctor.live.Recorder", side_effect=recorder), \
                        patch("servedoctor.live._decide", return_value={"incident": False}), \
                        patch.object(LogTail, "read", read):
                    with self.assertRaises(RecorderError):
                        run_live(self.scenario(), 0, arm="rules", clients={}, serving={}, pools={}, run_dir=run,
                                 engine_factory=factory, checkpoint_s=.005, extra_s=0, log=lambda *_: None)
                self.assertTrue(entered.is_set())
                result = json.loads((run / "live_result.json").read_text())
                self.assertEqual(result["failure"], "RecorderError")
                self.assertEqual(result["failure_stage"], "cleanup")
                stable_result = file_hash(run / "live_result.json")
                self.assertFalse(list(run.rglob("manifest.json")))
                before = (run / "telemetry.jsonl").read_bytes()
            finally:
                release.set()
                for item in recorders:
                    Recorder.stop(item)
            self.assertNotEqual((run / "telemetry.jsonl").read_bytes(), before)
            self.assertEqual(file_hash(run / "live_result.json"), stable_result)
            self.assertFalse(list(run.rglob("manifest.json")))

    def test_primary_error_survives_job_and_recorder_cleanup_failures(self):
        primary = KeyboardInterrupt(PRIVATE)
        failed = threading.Event()

        def read(_):
            failed.set()
            raise OSError(errno.EMFILE, PRIVATE)

        def interrupt(_):
            self.assertTrue(failed.wait(2))
            raise primary

        job = Mock()
        job.stop.side_effect = RuntimeError(PRIVATE)
        scenario = self.scenario()
        scenario["contention"] = {"onset_s": 60, "duty": .5, "matrix_size": 32}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("servedoctor.record.make_arrivals", return_value=[]), \
                    patch("servedoctor.record.Recorder", side_effect=lambda *a, **k: Recorder(*a, **k, scrape=lambda _: {})), \
                    patch.object(LogTail, "read", read):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    record_incident(scenario, engine=self.engine(root), pools={}, out_dir=root,
                                    sleeper=interrupt, job_factory=lambda: job)
            self.assertIs(caught.exception, primary)
            saved = self.check_failed(root, "KeyboardInterrupt")
            self.assertEqual(saved["failure_stage"], "record")
            self.assertEqual([e["resource"] for e in saved["cleanup_errors"]], ["job", "recorder"])
            job.stop.assert_called_once()

    def test_dispatch_thread_failure_reaches_wait_without_message_leak(self):
        row = {"id": "r1", "t": 0, "cls": "short", "prompt_tokens_est": 8}
        gateway = Mock()
        gateway.admit.side_effect = OSError(errno.EMFILE, PRIVATE)
        request = Mock()
        with patch("threading.excepthook") as hook:
            gen = LoadGenerator([row], gateway, request).start()
            with self.assertRaises(LoadGeneratorError) as caught:
                gen.wait()
            gen.stop()
            self.assertEqual(caught.exception.failure, "OSError")
            self.assertNotIn(PRIVATE, str(caught.exception))
            self.assertEqual(gen.outcomes, [])
            request.assert_not_called()
            hook.assert_not_called()

    def test_dispatch_failure_makes_recording_failed(self):
        row = {"id": "r1", "t": 0, "cls": "short", "prompt_tokens_est": 8}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("servedoctor.record.make_arrivals", return_value=[row]), \
                    patch.object(Gateway, "admit", side_effect=OSError(errno.EMFILE, PRIVATE)):
                with self.assertRaises(LoadGeneratorError):
                    record_incident(self.scenario(), engine=self.engine(root), pools={}, out_dir=root)
            saved = self.check_failed(root, "LoadGeneratorError")
            self.assertEqual(saved["failure_stage"], "loadgen_wait")
            self.assertEqual(saved["background_errors"], ["OSError"])
            self.assertEqual(saved["requests"]["requests"], 0)

    def test_successful_dispatch_preserves_normalized_outcomes(self):
        rows = [{"id": "r1", "t": 0, "cls": "short", "prompt_tokens_est": 8}]
        gen = LoadGenerator(rows, Gateway(), lambda _: {"status": "ok", "completion_tokens": 2}).start()
        gen.wait()
        gen.stop()
        self.assertIsNone(gen.dispatch_failure)
        self.assertEqual(len(gen.outcomes), 1)
        self.assertEqual(gen.outcomes[0]["status"], "ok")
        self.assertEqual(gen.outcomes[0]["completion_tokens"], 2)

    def test_study_preserves_record_failure_over_gpu_and_engine_cleanup(self):
        primary = RecorderError(["OSError"])
        sampler = Mock()
        sampler.stop.side_effect = RuntimeError(PRIVATE)
        engines = []

        def factory(_, path, dtype):
            path.mkdir(parents=True)
            engine = Mock(metadata={}, base_url="http://127.0.0.1:9/v1")
            engine.stop.side_effect = ValueError(PRIVATE)
            engines.append(engine)
            return engine

        with tempfile.TemporaryDirectory() as td, \
                patch("servedoctor.record.wait_idle", return_value=True), \
                patch("servedoctor.record.record_incident", side_effect=primary):
            with self.assertRaises(RecorderError) as caught:
                record_study([self.scenario()], serving={}, pools={}, out_dir=td,
                             engine_factory=factory, gpu_factory=lambda: sampler, log=lambda *_: None)
            self.assertIs(caught.exception, primary)
            failure = next(Path(td).glob("engines/*/failure.json"))
            saved = json.loads(failure.read_text())
            self.assertEqual(saved["stage"], "record_incident")
            self.assertEqual(saved["error"], "RecorderError")
            self.assertEqual(saved["cleanup_errors"], [{"resource": "gpu", "error": "RuntimeError"},
                                                      {"resource": "engine", "error": "ValueError"}])
            self.assertNotIn(PRIVATE, failure.read_text())
            self.assertTrue((failure.parent / "engine_metadata.json").exists())
            engines[0].stop.assert_called_once()
            sampler.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
