"""The judge-facing demo: recorded mode without a key, live mode with a fake transport."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from servedoctor import demo
from servedoctor.demo import run_demo, run_suite

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "results" / "servedoctor-hard-20261103" / "analysis"


def reply(decision, usage=(3000, 900)):
    def transport(body):
        transport.body = body
        return {"choices": [{"message": {"content": json.dumps(decision)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}}
    return transport


@unittest.skipUnless((STUDY / "incidents" / "hard-13").exists(), "published Hard-set evidence not present")
class DemoTests(unittest.TestCase):
    def test_keyless_mode_replays_the_recorded_reply(self):
        out = io.StringIO()
        record = run_demo(study_dir=STUDY, environ={}, out=out, color=False)
        text = out.getvalue()
        self.assertEqual(record["mode"], "recorded")
        self.assertIn("Recorded mode (no MODEL_API_KEY is set)", text)
        self.assertTrue(record["correct_cause"])
        self.assertFalse(record["stopped_decoy"])
        self.assertIn("the harmless decoy", text)

    def test_live_mode_calls_the_api_grades_and_saves_evidence(self):
        decision = {"incident": True, "root_cause": "gpu_contention", "confidence": 0.7,
                    "evidence": ["unknown GPU process"], "actions": [{"type": "stop_gpu_process", "pid": 5283}],
                    "explanation": "kill the neighbour"}
        transport = reply(decision)
        key = "test-key-0123456789abcdef"
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            record = run_demo(study_dir=STUDY, environ={"MODEL_API_KEY": key}, transport=transport, out=out,
                              color=False, evidence_dir=Path(tmp) / "demo", ledger_path=Path(tmp) / "ledger.json")
            text = out.getvalue()
            saved = list((Path(tmp) / "demo").glob("*-live.json"))
            self.assertEqual(len(saved), 1)
            self.assertNotIn(key, saved[0].read_text())
        self.assertEqual(record["mode"], "live")
        self.assertIn("Calling muse-spark-1.3 on the Meta Model API (live)", text)
        self.assertFalse(record["correct_cause"])
        self.assertTrue(record["stopped_decoy"])
        self.assertNotIn("answer", json.dumps(transport.body["messages"]).lower().replace("answers", ""))
        self.assertGreater(record["cost_usd"], 0)

    def test_invalid_reply_is_reported_not_graded(self):
        def transport(body):
            return {"choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 3000, "completion_tokens": 2048}}
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            record = run_demo(study_dir=STUDY, environ={"MODEL_API_KEY": "test-key-0123456789abcdef"},
                              transport=transport, out=out, color=False, evidence_dir=Path(tmp) / "demo",
                              ledger_path=Path(tmp) / "ledger.json")
        self.assertFalse(record["valid_output"])
        self.assertIn("not valid JSON", out.getvalue())


@unittest.skipUnless((STUDY / "incidents" / "hard-13").exists(), "published Hard-set evidence not present")
class SuiteTests(unittest.TestCase):
    KEY = "test-key-0123456789abcdef"

    def run_live(self, transport, tmp, **kwargs):
        out = io.StringIO()
        record = run_suite(study_dir=STUDY, environ={"MODEL_API_KEY": self.KEY}, transport=transport, out=out,
                           color=False, evidence_dir=Path(tmp) / "demo", ledger_path=Path(tmp) / "ledger.json",
                           **kwargs)
        return record, out.getvalue()

    def test_recorded_suite_reproduces_the_published_scoreboard(self):
        out = io.StringIO()
        record = run_suite(study_dir=STUDY, environ={}, out=out, color=False)
        self.assertEqual(record["mode"], "recorded")
        self.assertEqual(record["agent"], {"faults": 12, "diagnosed": 11, "safe_fixes": 11, "harmful": 0,
                                           "stopped_decoy": 0, "false_alarms": 0})
        self.assertEqual(record["rules"], {"faults": 12, "diagnosed": 7, "safe_fixes": 6, "harmful": 5,
                                           "stopped_decoy": 5, "false_alarms": 2})
        wonder = run_suite(study_dir=STUDY, model="wonder", environ={}, out=io.StringIO(), color=False)
        self.assertEqual(wonder["agent"]["diagnosed"], 10)
        self.assertIn("Recorded mode (no MODEL_API_KEY is set)", out.getvalue())

    def test_live_suite_calls_once_per_incident_scores_and_saves_evidence(self):
        bodies = []

        def transport(body):
            bodies.append(body)
            decision = {"incident": True, "root_cause": "traffic_surge", "confidence": 0.6, "evidence": ["load"],
                        "actions": [{"type": "gateway_rate_limit", "max_rps": 3.0}], "explanation": "shed load"}
            return {"choices": [{"message": {"content": json.dumps(decision)}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3000, "completion_tokens": 900}}

        with tempfile.TemporaryDirectory() as tmp:
            record, text = self.run_live(transport, tmp, workers=3)
            saved = list((Path(tmp) / "demo").glob("*-suite-live.json"))
            self.assertEqual(len(saved), 1)
            self.assertNotIn(self.KEY, saved[0].read_text())
            self.assertEqual(len(json.loads(saved[0].read_text())["incidents"]), 15)
        self.assertEqual(record["mode"], "live")
        self.assertEqual(len(bodies), 15)
        prompts = json.dumps([b["messages"] for b in bodies]).lower()
        for secret in ("root_causes", "decoy", "answer_key", "severity_index"):
            self.assertNotIn(secret, prompts)
        self.assertEqual(record["agent"]["diagnosed"], 3)       # hard-05, hard-08 and hard-13 include a surge
        self.assertEqual(record["agent"]["false_alarms"], 3)    # the three healthy controls
        self.assertEqual(record["failed_calls"], 0)
        self.assertGreater(record["cost_usd"], 0)
        self.assertIn("Sending 15 snapshots to muse-spark-1.3 on the Meta Model API (live), 3 at a time", text)

    def test_failed_calls_are_retried_reported_and_do_not_stop_the_run(self):
        calls = []

        def rate_limited(body):
            calls.append(1)
            raise urllib.error.HTTPError("https://api.meta.ai/v1/chat/completions", 429, "slow down", None, None)

        def unauthorized(body):
            calls.append(1)
            raise urllib.error.HTTPError("https://api.meta.ai/v1/chat/completions", 401, "no", None, None)

        saved_delays = demo.RETRY_DELAYS_S
        demo.RETRY_DELAYS_S = (0, 0)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                record, text = self.run_live(rate_limited, tmp)
            self.assertEqual(len(calls), 45)                    # three attempts per incident
            self.assertEqual(record["failed_calls"], 15)
            self.assertIn("error (HTTP 429)", text)
            calls.clear()
            with tempfile.TemporaryDirectory() as tmp:
                record, text = self.run_live(unauthorized, tmp)
            self.assertEqual(len(calls), 15)                    # a rejected key is not retried
            self.assertIn("error (HTTP 401)", text)
        finally:
            demo.RETRY_DELAYS_S = saved_delays


if __name__ == "__main__":
    unittest.main()
