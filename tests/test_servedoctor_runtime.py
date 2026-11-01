"""Runtime failure evidence checks using local stubs, never GPU/API results."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from servedoctor.live import EngineSlot, _execute, _rollback, run_live
from servedoctor.loadgen import Gateway
from servedoctor.llm import BudgetWarningError
from servedoctor.observe import load_incident
from servedoctor.record import calibrate, record_incident, record_study
from servedoctor.telemetry import read_jsonl


class StubEngine:
    def __init__(self, config, path, dtype):
        self.artifact_dir = Path(path)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.metadata = {}
        self.base_url = "http://127.0.0.1:9/v1"

    def start(self):
        return self

    def stop(self):
        pass


class ScriptedClient:
    def __init__(self, reply=None, error=None, ledger=None):
        self.reply, self.error, self.ledger = reply, error, ledger
        self.calls = 0

    def chat(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return json.dumps(self.reply), {"prompt_tokens": 100, "completion_tokens": 10}


class LiveEvidenceTests(unittest.TestCase):
    def test_failed_restart_rolls_back_prior_knob_in_fresh_generation(self):
        class RestartEngine(StubEngine):
            def __init__(self, config, path, dtype):
                super().__init__(config, path, dtype)
                self.config = config

            def start(self):
                if self.config["max_num_seqs"] == 64:
                    raise RuntimeError("simulated engine startup failure")
                return self

        with tempfile.TemporaryDirectory() as tmp:
            slot = EngineSlot(RestartEngine, {}, {"max_num_seqs": 4}, tmp)
            slot.start()
            gateway = Gateway()
            action = {"type": "set_engine_config", "knob": "max_num_seqs", "value": 64}
            executed = _execute(action, slot, gateway, None, lambda *_: None)
            self.assertEqual(executed["status"], "failed: RuntimeError")
            self.assertEqual(slot.generation, 1)
            result = {"executed": [executed]}
            _rollback(result, slot, gateway, lambda *_: None)
            self.assertTrue(result["rolled_back"])
            self.assertEqual(slot.knobs["max_num_seqs"], 4)
            self.assertEqual(slot.engine.config["max_num_seqs"], 4)
            self.assertEqual(slot.generation, 2)
            self.assertEqual([r["status"] for r in slot.restarts], ["failed", "completed"])
            slot.stop()

    def run_stub(self, run, clients, arm="spark"):
        scenario = {"id": "inc-stub", "duration_s": .04, "engine": {},
                    "slo": {"p95_latency_s": 10, "max_error_rate": .01},
                    "request_timeout_s": 1, "schedule": [{"start_s": 0, "rate_rps": 1,
                                                          "mix": {"short": 1}}],
                    "workload_seed": 1, "max_output_tokens": 8, "events": []}
        return run_live(scenario, 0, arm=arm, clients=clients, pools={"short": ["Compute 1 + 1"]},
                        run_dir=run, serving={}, engine_factory=StubEngine,
                        checkpoint_s=.01, extra_s=0, log=lambda *_: None)

    def test_failed_calls_and_non_incidents_survive_in_checkpoint_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            client = ScriptedClient(error=TimeoutError())
            result = self.run_stub(run, {"spark": client})
            journal = read_jsonl(run / "checkpoints.jsonl")
            self.assertGreater(len(journal), 0)
            self.assertEqual(client.calls, len(journal))
            self.assertEqual(journal, result["trail"])
            self.assertTrue(all(s["error"] == "TimeoutError" and s["decision"]["call_failed"]
                                for s in journal))
            self.assertTrue(all(len(s["observation_sha256"]) == 64 for s in journal))

    def test_monitor_usage_is_saved_when_expert_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            monitor = ScriptedClient({"status": "anomaly", "summary": "queue rising"})
            expert = ScriptedClient(error=ConnectionError())
            self.run_stub(run, {"glimmer": monitor, "spark": expert}, arm="glimmer_to_spark")
            journal = read_jsonl(run / "checkpoints.jsonl")
            self.assertTrue(all(s["monitor"]["usage"]["prompt_tokens"] == 100 for s in journal))
            self.assertTrue(all(s["escalated"] and s["error"] == "ConnectionError" for s in journal))

    def test_budget_warning_stops_after_saving_reply_and_failure_result(self):
        class WarnedLedger:
            def require_below_warning(self):
                raise BudgetWarningError("meta at 50%")

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            client = ScriptedClient({"incident": False, "root_cause": "healthy"}, ledger=WarnedLedger())
            with self.assertRaises(BudgetWarningError):
                self.run_stub(run, {"spark": client})
            journal = read_jsonl(run / "checkpoints.jsonl")
            self.assertEqual(len(journal), 1)
            self.assertEqual(journal[0]["decision"]["usage"]["prompt_tokens"], 100)
            saved = json.loads((run / "live_result.json").read_text())
            self.assertEqual(saved["failure"], "BudgetWarningError")
            self.assertEqual(saved["trail"], journal)
            self.assertTrue((run / "requests.jsonl").exists())


class RecordingEvidenceTests(unittest.TestCase):
    def test_failed_start_preserves_calibration_and_engine_metadata(self):
        class BrokenEngine(StubEngine):
            stopped = False

            def start(self):
                raise RuntimeError("simulated startup failure")

            def stop(self):
                BrokenEngine.stopped = True

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "calibration"
            with self.assertRaises(RuntimeError):
                calibrate(serving={}, study={"engine_base": {}}, pools={}, out_dir=out,
                          engine_factory=BrokenEngine, rates=[2])
            result = json.loads((out / "calibration.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failure"], "RuntimeError")
            self.assertIsNone(result["capacity_rps"])
            self.assertTrue(BrokenEngine.stopped)
            self.assertTrue((out / "engine" / "engine_metadata.json").exists())

    def test_non_idle_engine_never_records_next_incident(self):
        scenario = {"id": "inc-stub", "engine": {}}
        with tempfile.TemporaryDirectory() as tmp:
            with patch("servedoctor.record.wait_idle", return_value=False), \
                    patch("servedoctor.record.record_incident") as record:
                with self.assertRaises(RuntimeError):
                    record_study([scenario], serving={}, pools={}, out_dir=tmp,
                                 engine_factory=StubEngine, log=lambda *_: None)
                record.assert_not_called()
            failure = json.loads(next(Path(tmp).glob("engines/*/failure.json")).read_text())
            self.assertEqual(failure["stage"], "wait_idle")
            self.assertEqual(failure["incident_id"], "inc-stub")

    def test_interrupted_recording_is_saved_and_cannot_be_evaluated(self):
        scenario = {"id": "inc-stub", "duration_s": 1, "engine": {}, "events": [],
                    "slo": {"p95_latency_s": 10, "max_error_rate": .01}, "request_timeout_s": 1}

        def interrupt(_):
            raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as tmp:
            engine = StubEngine({}, Path(tmp) / "engine", "bf16")
            with patch("servedoctor.record.make_arrivals", return_value=[]):
                with self.assertRaises(KeyboardInterrupt):
                    record_incident(scenario, engine=engine, pools={}, out_dir=tmp, sleeper=interrupt)
            inc = Path(tmp) / "incidents" / "inc-stub"
            result = json.loads((inc / "recording.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failure"], "KeyboardInterrupt")
            self.assertTrue((inc / "requests.jsonl").exists())
            self.assertTrue((inc / "manifest.json").exists())
            with self.assertRaises(ValueError):
                load_incident(inc)


if __name__ == "__main__":
    unittest.main()
