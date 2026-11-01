import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from servedoctor.evaluate import evaluate
from servedoctor.llm import BudgetWarningError, Ledger, ModelClient


class BudgetSafeguardTests(unittest.TestCase):
    def test_warning_blocks_dispatch_without_another_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "ledger.json")
            ledger.initialize()
            ledger.reserve("meta", Decimal("25"), {"test": True})
            sent = []
            client = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "test-only"},
                                 transport=lambda body: sent.append(body))
            with self.assertRaises(BudgetWarningError):
                client.chat("system", "user")
            self.assertEqual(sent, [])
            self.assertEqual(ledger.summary()["calls"], 1)

    def test_baseten_requires_verified_positive_prices(self):
        for bad in (None, "0", "-1", "NaN", "Infinity"):
            with self.subTest(price=bad):
                environ = {"BASETEN_API_KEY": "test-only", "BASETEN_OUTPUT_PER_M": "2"}
                if bad is not None:
                    environ["BASETEN_INPUT_PER_M"] = bad
                with self.assertRaises(ValueError):
                    ModelClient("glimmer-baseten", ledger=object(), environ=environ)

    def test_crossing_warning_preserves_checkpoint_and_blocks_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "incidents" / "inc-01").mkdir(parents=True)
            ledger = Ledger(root / "ledger.json")
            ledger.initialize()
            ledger.reserve("meta", Decimal("24.999"), {"test": True})
            sent = []

            def transport(body):
                sent.append(body)
                return {"choices": [{"message": {"content": json.dumps({
                    "incident": True, "root_cause": "traffic_surge",
                    "actions": [{"type": "gateway_rate_limit", "max_rps": 2}]
                })}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}

            client = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "test-only"},
                                 transport=transport)
            incident = {"id": "inc-01", "engine_config": {}, "telemetry": [], "events": [],
                        "slo": {}, "recording": {"duration_s": 120}}
            with patch("servedoctor.evaluate.load_incident", return_value=incident):
                with self.assertRaises(BudgetWarningError):
                    evaluate(root, ["spark"], clients={"spark": client}, log=lambda *_: None)
                partial = root / "decisions" / "spark" / "inc-01.partial.json"
                saved = json.loads(partial.read_text())
                self.assertTrue(saved["incomplete"])
                self.assertEqual(saved["trail"][0]["decision"]["usage"]["prompt_tokens"], 1000)
                self.assertEqual(saved["final"]["root_cause"], "traffic_surge")
                self.assertFalse((partial.parent / "inc-01.json").exists())
                with self.assertRaisesRegex(RuntimeError, "Incomplete evaluation preserved"):
                    evaluate(root, ["spark"], clients={"spark": client}, log=lambda *_: None)
            self.assertEqual(len(sent), 1)

    def test_completed_evaluation_promotes_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "incidents" / "inc-01").mkdir(parents=True)
            incident = {"id": "inc-01", "engine_config": {}, "telemetry": [], "events": [],
                        "slo": {}, "recording": {"duration_s": 30}}
            with patch("servedoctor.evaluate.load_incident", return_value=incident):
                evaluate(root, ["rules"], clients={}, log=lambda *_: None)
            self.assertTrue((root / "decisions" / "rules" / "inc-01.json").exists())
            self.assertFalse((root / "decisions" / "rules" / "inc-01.partial.json").exists())

    def test_interrupted_evaluation_keeps_previous_paid_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "incidents" / "inc-01").mkdir(parents=True)
            ledger = Ledger(root / "ledger.json")
            ledger.initialize()
            sent = []

            def transport(body):
                sent.append(body)
                if len(sent) == 2:
                    raise KeyboardInterrupt()
                return {"choices": [{"message": {"content": json.dumps({
                    "incident": False, "root_cause": "healthy"
                })}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}

            client = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "test-only"},
                                 transport=transport)
            incident = {"id": "inc-01", "engine_config": {}, "telemetry": [], "events": [],
                        "slo": {}, "recording": {"duration_s": 120}}
            with patch("servedoctor.evaluate.load_incident", return_value=incident):
                with self.assertRaises(KeyboardInterrupt):
                    evaluate(root, ["spark"], clients={"spark": client}, log=lambda *_: None)
                saved = json.loads((root / "decisions" / "spark" / "inc-01.partial.json").read_text())
                self.assertEqual(saved["checkpoints"], 1)
                self.assertEqual(saved["trail"][0]["decision"]["usage"]["prompt_tokens"], 1000)
                with self.assertRaisesRegex(RuntimeError, "Incomplete evaluation preserved"):
                    evaluate(root, ["spark"], clients={"spark": client}, log=lambda *_: None)
            self.assertEqual(len(sent), 2)
            self.assertEqual(ledger.summary()["calls"], 2)


if __name__ == "__main__":
    unittest.main()
