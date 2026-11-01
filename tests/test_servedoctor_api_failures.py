import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from servedoctor.evaluate import evaluate, run_incident
from servedoctor.llm import Ledger, ModelClient, PermanentAPIError


INCIDENT = {"id": "inc-01", "engine_config": {}, "telemetry": [], "events": [],
            "slo": {}, "recording": {"duration_s": 120}}


class PaidAPIErrorTests(unittest.TestCase):
    def test_permanent_paid_error_stops_after_one_dispatch_and_preserves_reservation(self):
        for status in (400, 401, 403, 404, 429):
            with self.subTest(http_status=status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "incidents" / "inc-01").mkdir(parents=True)
                ledger = Ledger(root / "ledger.json")
                ledger.initialize()
                sent = []
                invented_secret = "offline-only-secret-0123456789"

                def transport(body):
                    sent.append(body)
                    raise HTTPError("https://invalid.example/" + invented_secret, status,
                                    invented_secret, {}, None)

                client = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": invented_secret},
                                     transport=transport)
                with patch("servedoctor.evaluate.load_incident", return_value=INCIDENT):
                    with self.assertRaises(PermanentAPIError) as raised:
                        evaluate(root, ["spark"], clients={"spark": client}, log=lambda *_: None)
                    self.assertNotIn(invented_secret, str(raised.exception))
                    saved_text = (root / "decisions" / "spark" / "inc-01.partial.json").read_text()
                    self.assertNotIn(invented_secret, saved_text)
                    saved = json.loads(saved_text)
                    self.assertEqual(saved["checkpoints"], 1)
                    self.assertEqual(saved["trail"][0]["http_status"], status)
                    self.assertEqual(saved["trail"][0]["provider"], "meta")
                    self.assertTrue(saved["trail"][0]["decision"]["call_failed"])
                    self.assertFalse((root / "decisions" / "spark" / "inc-01.json").exists())
                    with self.assertRaisesRegex(RuntimeError, "Incomplete evaluation preserved"):
                        evaluate(root, ["spark"], clients={"spark": client}, log=lambda *_: None)
                self.assertEqual(len(sent), 1)
                self.assertEqual(ledger.summary()["calls"], 1)
                self.assertGreater(ledger.summary()["accounted_usd"]["meta"], 0)
                self.assertEqual(json.loads(ledger.path.read_text())["entries"][0]["status"], "reserved")

    def test_local_glimmer_http_failure_keeps_existing_checkpoint_policy(self):
        sent = []

        def transport(body):
            sent.append(body)
            raise HTTPError("http://127.0.0.1:8000/chat/completions", 400, "invalid", {}, None)

        client = ModelClient("glimmer-local", transport=transport)
        result = run_incident("glimmer", INCIDENT, profile=None, reference_config=None,
                              clients={"glimmer": client}, checkpoint_s=30)
        self.assertEqual(len(sent), 4)
        self.assertTrue(all(step["error"] == "HTTPError" for step in result["trail"]))


if __name__ == "__main__":
    unittest.main()
