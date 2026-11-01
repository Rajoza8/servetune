import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from servedoctor.evaluate import run_incident
from servedoctor.llm import Ledger, ModelClient, PermanentAPIError


INCIDENT = {"id": "inc-01", "engine_config": {}, "telemetry": [], "events": [],
            "slo": {}, "recording": {"duration_s": 120}}


def reply(value):
    return {"choices": [{"message": {"content": json.dumps(value)}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}


class MonitorFailoverTests(unittest.TestCase):
    def test_local_monitor_failure_is_preserved_and_escalates_once(self):
        for error in (TimeoutError(), HTTPError("http://127.0.0.1:8000", 400, "context", {}, None)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                ledger = Ledger(Path(tmp) / "ledger.json")
                ledger.initialize()

                def broken(body):
                    raise error

                monitor = ModelClient("glimmer-local", transport=broken)
                expert = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "offline-only"},
                                     transport=lambda body: reply({"incident": True,
                                         "root_cause": "traffic_surge", "actions": [
                                             {"type": "gateway_rate_limit", "max_rps": 2}]}))
                result = run_incident("glimmer_to_spark", INCIDENT, profile=None, reference_config=None,
                                      clients={"glimmer": monitor, "spark": expert}, checkpoint_s=30)
                self.assertEqual(monitor.calls, 1)
                self.assertEqual(expert.calls, 1)
                step = result["trail"][0]
                self.assertEqual(step["error"], type(error).__name__)
                self.assertEqual(step["monitor"]["error"], type(error).__name__)
                self.assertTrue(step["monitor"]["call_failed"])
                self.assertTrue(step["escalated"])
                self.assertTrue(step["decision"]["valid_output"])
                self.assertEqual(result["final"]["root_cause"], "traffic_surge")
                if isinstance(error, HTTPError):
                    self.assertEqual(step["http_status"], 400)
                    self.assertEqual(step["monitor"]["http_status"], 400)

    def test_healthy_monitor_still_skips_expert(self):
        monitor = ModelClient("glimmer-local", transport=lambda body: reply({"status": "healthy"}))
        result = run_incident("glimmer_to_spark", dict(INCIDENT, recording={"duration_s": 30}),
                              profile=None, reference_config=None, clients={"glimmer": monitor}, checkpoint_s=30)
        self.assertEqual(monitor.calls, 1)
        self.assertNotIn("escalated", result["trail"][0])
        self.assertIsNone(result["final"])

    def test_paid_monitor_rejection_stops_instead_of_spending_on_expert(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "ledger.json")
            ledger.initialize()

            def rejected(body):
                raise HTTPError("https://invalid.example", 401, "credentials", {}, None)

            monitor = ModelClient("glimmer-baseten", ledger=ledger, transport=rejected,
                                  environ={"BASETEN_API_KEY": "offline-only", "BASETEN_INPUT_PER_M": "1",
                                           "BASETEN_OUTPUT_PER_M": "2"})
            trail = []
            with self.assertRaises(PermanentAPIError):
                run_incident("glimmer_to_spark", INCIDENT, profile=None, reference_config=None,
                             clients={"glimmer": monitor}, checkpoint_s=30, on_step=trail.append)
            self.assertEqual(monitor.calls, 1)
            self.assertEqual(trail[0]["trail"][0]["http_status"], 401)
            self.assertNotIn("escalated", trail[0]["trail"][0])


if __name__ == "__main__":
    unittest.main()
