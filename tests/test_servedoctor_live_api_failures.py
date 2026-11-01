"""Live rejection/fallback evidence with fake transports, never paid requests."""
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from servedoctor.live import run_live
from servedoctor.llm import Ledger, ModelClient, PermanentAPIError
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


def run_stub(run, clients, arm):
    scenario = {"id": "inc-stub", "duration_s": .04, "engine": {"max_model_len": 1024},
                "slo": {"p95_latency_s": 10, "max_error_rate": .01}, "request_timeout_s": 1,
                "schedule": [{"start_s": 0, "rate_rps": 1, "mix": {"short": 1}}],
                "workload_seed": 1, "max_output_tokens": 8, "events": []}
    return run_live(scenario, 0, arm=arm, clients=clients, pools={"short": ["Compute 1 + 1"]},
                    run_dir=run, serving={}, engine_factory=StubEngine,
                    checkpoint_s=.01, extra_s=0, log=lambda *_: None)


class LiveApiFailureTests(unittest.TestCase):
    def test_paid_http_rejection_is_journaled_once_then_stops_live_run(self):
        for status in (400, 401, 403, 404, 429):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ledger = Ledger(root / "ledger.json")
                ledger.initialize()

                def rejected(body):
                    raise urllib.error.HTTPError("https://provider.invalid", status, "rejected", {}, None)

                expert = ModelClient("spark", ledger=ledger, transport=rejected,
                                     environ={"MODEL_API_KEY": "dummy-test-key-no-real-credential"})
                clients, arm = {"spark": expert}, "spark"
                if status == 403:
                    def failed_monitor(body):
                        raise urllib.error.HTTPError("http://127.0.0.1:9/v1", 400, "context too long", {}, None)
                    monitor = ModelClient("glimmer-local", transport=failed_monitor)
                    clients["glimmer"], arm = monitor, "glimmer_to_spark"
                run = root / "run"
                with self.assertRaises(PermanentAPIError) as caught:
                    run_stub(run, clients, arm)
                self.assertEqual(caught.exception.http_status, status)
                self.assertEqual(expert.calls, 1)
                self.assertEqual(ledger.summary()["calls"], 1)
                self.assertGreater(ledger.summary()["accounted_usd"]["meta"], 0)
                journal = read_jsonl(run / "checkpoints.jsonl")
                self.assertEqual(len(journal), 1)
                self.assertEqual(journal[0]["http_status"], status)
                self.assertEqual(journal[0]["provider"], "meta")
                self.assertTrue(journal[0]["decision"]["call_failed"])
                if status == 403:
                    self.assertEqual(monitor.calls, 1)
                    self.assertEqual(journal[0]["monitor"]["http_status"], 400)
                    self.assertTrue(journal[0]["escalated"])
                saved = json.loads((run / "live_result.json").read_text())
                self.assertEqual(saved["failure"], "PermanentAPIError")
                self.assertEqual(saved["http_status"], status)

    def test_failed_local_monitor_escalates_same_observation_once_and_applies_fix(self):
        failures = [urllib.error.HTTPError("http://127.0.0.1:9/v1", 400, "context too long", {}, None),
                    TimeoutError(), urllib.error.URLError("offline")]
        for failure in failures:
            with self.subTest(error=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                requests = {"monitor": [], "expert": []}

                def broken_monitor(body):
                    requests["monitor"].append(body)
                    raise failure

                def expert_reply(body):
                    requests["expert"].append(body)
                    decision = {"incident": True, "root_cause": "context_limit_too_small",
                                "actions": [{"type": "set_engine_config", "knob": "max_model_len", "value": 4096}]}
                    return {"choices": [{"message": {"content": json.dumps(decision)}}],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 10}}

                monitor = ModelClient("glimmer-local", transport=broken_monitor)
                # A local fake expert isolates live orchestration from the ledger test above.
                expert = ModelClient("glimmer-local", transport=expert_reply)
                run = Path(tmp) / "run"
                result = run_stub(run, {"glimmer": monitor, "spark": expert}, "glimmer_to_spark")
                self.assertEqual(monitor.calls, 1)
                self.assertEqual(expert.calls, 1)
                self.assertEqual(requests["monitor"][0]["messages"][-1],
                                 requests["expert"][0]["messages"][-1])
                journal = read_jsonl(run / "checkpoints.jsonl")
                self.assertEqual(len(journal), 1)
                self.assertTrue(journal[0]["monitor"]["call_failed"])
                self.assertEqual(journal[0]["monitor"]["error"], type(failure).__name__)
                if isinstance(failure, urllib.error.HTTPError):
                    self.assertEqual(journal[0]["monitor"]["http_status"], 400)
                self.assertTrue(journal[0]["escalated"])
                self.assertEqual(result["executed"][0]["status"], "executed")
                self.assertEqual(result["engine_restarts"][0]["value"], 4096)


if __name__ == "__main__":
    unittest.main()
