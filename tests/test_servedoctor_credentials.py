import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from servedoctor.evaluate import evaluate, run_incident
from servedoctor.llm import Ledger, ModelClient, PermanentConfigurationError


INCIDENT = {"id": "inc-01", "engine_config": {}, "telemetry": [], "events": [],
            "slo": {}, "recording": {"duration_s": 120}}


class CredentialTests(unittest.TestCase):
    def test_invalid_paid_credentials_fail_before_any_reservation(self):
        invalid = [None, "", "invented-key-\u00e9", "invented-key\n", "invented key",
                   " invented-key", "invented-key\t", "invented-key\x00", "invented-key\x7f", b"invented-key", 42]
        for client_name in ("spark", "wonder", "glimmer-baseten"):
            for index, key in enumerate(invalid):
                with self.subTest(client=client_name, case=index), tempfile.TemporaryDirectory() as tmp:
                    ledger = Ledger(Path(tmp) / "ledger.json")
                    ledger.initialize()
                    before = ledger.path.read_bytes()
                    environ = {"MODEL_API_KEY": key, "BASETEN_API_KEY": key,
                               "BASETEN_INPUT_PER_M": "1", "BASETEN_OUTPUT_PER_M": "2"}
                    with self.assertRaises(ValueError) as caught:
                        ModelClient(client_name, ledger=ledger, environ=environ,
                                    transport=lambda _: self.fail("Invalid credential reached transport"))
                    self.assertEqual(str(caught.exception), "Paid API credentials must be nonempty ASCII strings without whitespace or control characters")
                    self.assertEqual(ledger.path.read_bytes(), before)
                    self.assertEqual(ledger.summary()["calls"], 0)

    def test_valid_ascii_test_credential_still_dispatches_and_settles(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "ledger.json")
            ledger.initialize()
            client = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "invented-ascii:key_0123456789-+="},
                                 transport=lambda _: {"choices": [{"message": {"content": "{}"}}],
                                                      "usage": {"prompt_tokens": 100, "completion_tokens": 10}})
            self.assertEqual(client.chat("system", "user")[0], "{}")
            self.assertEqual(client.calls, 1)
            self.assertEqual(ledger.summary()["calls"], 1)
            self.assertEqual(json.loads(ledger.path.read_text())["entries"][0]["status"], "settled")

    def test_paid_transport_encoding_failure_is_journaled_once_then_halts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "incidents" / "inc-01").mkdir(parents=True)
            ledger = Ledger(root / "ledger.json")
            ledger.initialize()
            private_fixture = "invented-private-\u00e9-value"

            def broken(_):
                raise UnicodeEncodeError("ascii", private_fixture, 0, 1, "fixture encoding failure")

            client = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "invented-valid-ascii-key"},
                                 transport=broken)
            with patch("servedoctor.evaluate.load_incident", return_value=INCIDENT):
                with self.assertRaises(PermanentConfigurationError) as caught:
                    evaluate(root, ["spark"], clients={"spark": client}, log=lambda *_: None)
                self.assertNotIn(private_fixture, str(caught.exception))
                path = root / "decisions" / "spark" / "inc-01.partial.json"
                self.assertNotIn(private_fixture, path.read_text())
                saved = json.loads(path.read_text())
                self.assertEqual(saved["checkpoints"], 1)
                self.assertEqual(saved["trail"][0]["error"], "PermanentConfigurationError")
                self.assertEqual(saved["trail"][0]["provider"], "meta")
                self.assertTrue(saved["trail"][0]["decision"]["call_failed"])
                with self.assertRaisesRegex(RuntimeError, "Incomplete evaluation preserved"):
                    evaluate(root, ["spark"], clients={"spark": client}, log=lambda *_: None)
            self.assertEqual(client.calls, 1)
            self.assertEqual(ledger.summary()["calls"], 1)
            self.assertEqual(json.loads(ledger.path.read_text())["entries"][0]["status"], "reserved")

    def test_local_monitor_encoding_failure_halts_without_an_expert_call(self):
        def broken(_):
            raise UnicodeEncodeError("ascii", "invented-\u00e9", 0, 1, "fixture failure")

        monitor = ModelClient("glimmer-local", transport=broken)
        expert = ModelClient("glimmer-local", transport=lambda _: self.fail("Encoding failure escalated"))
        progress = []
        with self.assertRaises(PermanentConfigurationError):
            run_incident("glimmer_to_spark", INCIDENT, profile=None, reference_config=None,
                         clients={"glimmer": monitor, "spark": expert}, checkpoint_s=30, on_step=progress.append)
        self.assertEqual(monitor.calls, 1)
        self.assertEqual(expert.calls, 0)
        self.assertEqual(progress[0]["trail"][0]["error"], "PermanentConfigurationError")


if __name__ == "__main__":
    unittest.main()
