"""Initialization failure cleanup with local fakes, never GPU or network calls."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from servedoctor.live import run_live
from servedoctor.loadgen import LoadGenerator


class SetupFailure(RuntimeError):
    pass


class CleanupFailure(RuntimeError):
    pass


class FakeEngine:
    def __init__(self, config, path, dtype):
        self.artifact_dir = Path(path)
        self.artifact_dir.mkdir(parents=True)
        self.metadata = {}
        self.base_url = "http://127.0.0.1:9/v1"
        self.started = self.stopped = False

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True


class LiveInitializationTests(unittest.TestCase):
    def scenario(self):
        return {"id": "inc-initialization-stub", "duration_s": 1, "engine": {},
                "slo": {"p95_latency_s": 10, "max_error_rate": .01},
                "request_timeout_s": 1, "events": []}

    def invoke(self, path, factory, gpu_factory=None):
        return run_live(self.scenario(), 0, arm="rules", clients={}, serving={}, pools={},
                        run_dir=path, engine_factory=factory, gpu_factory=gpu_factory,
                        extra_s=0, log=lambda *_: None)

    def check_evidence(self, path, stage, primary="SetupFailure"):
        result = json.loads((path / "live_result.json").read_text())
        self.assertEqual(result["failure"], primary)
        self.assertEqual(result["failure_stage"], stage)
        self.assertEqual(result["trail"], [])
        self.assertTrue((path / "checkpoints.jsonl").is_file())
        self.assertEqual((path / "requests.jsonl").read_text(), "")
        self.assertNotIn("private-injected-detail", json.dumps(result))
        return result

    def test_engine_start_failure_stops_owned_engine_and_retains_result(self):
        engines = []
        failure = SetupFailure("private-injected-detail")

        def factory(*args):
            engine = FakeEngine(*args)
            engines.append(engine)
            engine.start = Mock(side_effect=failure)
            return engine

        sampler = Mock()
        with tempfile.TemporaryDirectory() as td, patch("servedoctor.live.make_arrivals") as arrivals:
            path = Path(td) / "run"
            with self.assertRaises(SetupFailure) as caught:
                self.invoke(path, factory, sampler)
            self.assertIs(caught.exception, failure)
            self.assertTrue(engines[0].stopped)
            sampler.assert_not_called()
            arrivals.assert_not_called()
            self.assertTrue((path / "engines/engine-0/engine_metadata.json").exists())
            self.check_evidence(path, "engine_start")

    def test_workload_setup_failure_cleans_engine_before_other_factories(self):
        engines = []

        def factory(*args):
            engine = FakeEngine(*args)
            engines.append(engine)
            return engine

        sampler = Mock()
        with tempfile.TemporaryDirectory() as td, \
                patch("servedoctor.live.make_arrivals", side_effect=SetupFailure("private-injected-detail")), \
                patch("servedoctor.live.Recorder") as recorder:
            path = Path(td) / "run"
            with self.assertRaises(SetupFailure):
                self.invoke(path, factory, sampler)
            self.assertTrue(engines[0].started and engines[0].stopped)
            sampler.assert_not_called()
            recorder.assert_not_called()
            self.check_evidence(path, "workload_setup")

    def test_gpu_factory_failure_stops_engine_and_unstarted_generator_safely(self):
        engines, generators = [], []

        def factory(*args):
            engine = FakeEngine(*args)
            engines.append(engine)
            return engine

        def generator(*args):
            instance = LoadGenerator(*args)
            generators.append(instance)
            return instance

        failure = SetupFailure("private-injected-detail")
        with tempfile.TemporaryDirectory() as td, patch("servedoctor.live.make_arrivals", return_value=[]), \
                patch("servedoctor.live.LoadGenerator", side_effect=generator), \
                patch("servedoctor.live.Recorder") as recorder:
            path = Path(td) / "run"
            with self.assertRaises(SetupFailure) as caught:
                self.invoke(path, factory, Mock(side_effect=failure))
            self.assertIs(caught.exception, failure)
            self.assertTrue(engines[0].stopped)
            self.assertIsNone(generators[0]._thread)
            self.assertIsNone(generators[0]._pool)
            self.assertTrue(generators[0]._stop.is_set())
            recorder.assert_not_called()
            self.assertEqual(self.check_evidence(path, "gpu_setup")["cleanup_errors"], [])

    def test_recorder_start_failure_attempts_all_cleanup_and_preserves_primary(self):
        engines, recorders = [], []
        sampler = Mock()
        failure = SetupFailure("private-injected-detail")

        def factory(*args):
            engine = FakeEngine(*args)
            engines.append(engine)
            engine.stop = Mock(side_effect=CleanupFailure("private-injected-detail"))
            return engine

        class UnstartedRecorder:
            def __init__(self, *args, **kwargs):
                self._thread = threading.Thread(target=lambda: None)
                self._stop = threading.Event()
                recorders.append(self)

            def start(self):
                raise failure

            def stop(self):
                raise AssertionError("Must not join an unstarted recorder thread")

        with tempfile.TemporaryDirectory() as td, patch("servedoctor.live.make_arrivals", return_value=[]), \
                patch("servedoctor.live.Recorder", UnstartedRecorder):
            path = Path(td) / "run"
            with self.assertRaises(SetupFailure) as caught:
                self.invoke(path, factory, lambda: sampler)
            self.assertIs(caught.exception, failure)
            engines[0].stop.assert_called_once()
            sampler.stop.assert_called_once()
            self.assertTrue(recorders[0]._stop.is_set())
            result = self.check_evidence(path, "recorder_start")
            self.assertEqual(result["cleanup_errors"], [{"resource": "engine", "error": "CleanupFailure"}])

    def test_loadgen_start_failure_stops_already_started_resources(self):
        engines, generators, recorders = [], [], []
        sampler = Mock()

        def factory(*args):
            engine = FakeEngine(*args)
            engines.append(engine)
            return engine

        class BrokenGenerator:
            def __init__(self, *args):
                self.outcomes = []
                self.stopped = False
                generators.append(self)

            def start(self, **kwargs):
                raise SetupFailure("private-injected-detail")

            def stop(self):
                self.stopped = True

        class FakeRecorder:
            def __init__(self, *args, **kwargs):
                self.started = self.stopped = False
                recorders.append(self)

            def start(self):
                self.started = True

            def stop(self):
                self.stopped = True

        with tempfile.TemporaryDirectory() as td, patch("servedoctor.live.make_arrivals", return_value=[]), \
                patch("servedoctor.live.LoadGenerator", BrokenGenerator), patch("servedoctor.live.Recorder", FakeRecorder):
            path = Path(td) / "run"
            with self.assertRaises(SetupFailure):
                self.invoke(path, factory, lambda: sampler)
            self.assertTrue(engines[0].stopped and generators[0].stopped)
            self.assertTrue(recorders[0].started and recorders[0].stopped)
            sampler.stop.assert_called_once()
            self.assertEqual(self.check_evidence(path, "loadgen_start")["cleanup_errors"], [])


if __name__ == "__main__":
    unittest.main()
