"""The judge-facing demo: recorded mode without a key, live mode with a fake transport."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from servedoctor.demo import run_demo

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


if __name__ == "__main__":
    unittest.main()
