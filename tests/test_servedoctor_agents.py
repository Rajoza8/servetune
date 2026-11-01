import copy
import json
from pathlib import Path
import tempfile
import unittest

from servedoctor import scenarios
from servedoctor.evaluate import evaluate
from servedoctor.fakeserve import FakeServer
from servedoctor.live import run_live
from servedoctor.llm import Ledger, LedgerError, ModelClient, normalize_decision, parse_json
from servedoctor.observe import load_incident, normal_profile, observe, render
from servedoctor.scoring import score_study
from servedoctor.simulate import simulate_study

STUDY = json.loads((Path(__file__).resolve().parents[1] / "configs" / "servedoctor.json").read_text())


def sim_study(tmp):
    study = copy.deepcopy(STUDY)
    study["capacity_rps"] = 10
    simulate_study(study, tmp)
    return study


def scripted_transport(decision, usage=(1000, 200)):
    calls = []

    def transport(body):
        calls.append(body)
        return {"choices": [{"message": {"content": json.dumps(decision)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}}

    transport.calls = calls
    return transport


class ObservationTests(unittest.TestCase):
    def test_no_look_ahead(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim_study(tmp)
            incident = load_incident(Path(tmp) / "incidents" / "inc-01")
            early = observe(incident, 60)
            self.assertTrue(all(b["t_end"] <= 60 for b in early["recent_10s_buckets"]))
            self.assertTrue(all(e["t"] <= 60 for e in early["change_log"]))
            text = render(early)
            self.assertIn("recent_10s_buckets", text)
            for cause in ("traffic_surge", "gpu_contention", "kv_cache_starvation"):
                self.assertNotIn(cause, text)

    def test_profile_from_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim_study(tmp)
            profile = normal_profile(load_incident(Path(tmp) / "incidents" / "reference")["telemetry"])
            self.assertGreater(profile["arrivals_rps"], 2)


class DecisionParsingTests(unittest.TestCase):
    def test_invalid_actions_are_rejected_not_executed(self):
        raw = {"incident": True, "root_cause": "batch_limit_too_low",
               "actions": [{"type": "shell", "cmd": "reboot"},
                           {"type": "set_engine_config", "knob": "max_num_seqs", "value": 64}]}
        decision = normalize_decision(raw, current_config={"max_num_seqs": 4})
        self.assertEqual(decision["actions"], [{"type": "set_engine_config", "knob": "max_num_seqs", "value": 64}])
        self.assertEqual(len(decision["rejected_actions"]), 1)
        self.assertEqual(parse_json('Here: ```json\n{"a": 1}\n```')["a"], 1)
        unknown = normalize_decision({"incident": True, "root_cause": "aliens"}, current_config={})
        self.assertEqual(unknown["root_cause"], "other")
        self.assertEqual(unknown["actions"], [{"type": "escalate_to_human"}])


class LedgerTests(unittest.TestCase):
    def test_reserve_settle_and_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "ledger.json")
            with self.assertRaises(LedgerError):
                ledger.summary()
            ledger.initialize()
            with self.assertRaises(LedgerError):
                ledger.initialize()
            client = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "secret-key-0123456789abcdef"},
                                 transport=scripted_transport({"incident": False, "root_cause": "healthy",
                                                               "explanation": "secret-key-0123456789abcdef"}))
            text, usage = client.chat("s", "u")
            self.assertNotIn("secret-key-0123456789abcdef", text)
            summary = ledger.summary()
            self.assertAlmostEqual(summary["accounted_usd"]["meta"], (1000 * 1.25 + 200 * 4.25) / 1e6)
            from decimal import Decimal
            with self.assertRaises(LedgerError):
                ledger.reserve("meta", Decimal("60"), {})

    def test_failed_call_keeps_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "ledger.json")
            ledger.initialize()

            def broken(body):
                raise TimeoutError()

            client = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "test-key-0123456789abcdef"}, transport=broken)
            with self.assertRaises(TimeoutError):
                client.chat("s", "u", max_tokens=1000)
            self.assertGreater(ledger.summary()["accounted_usd"]["meta"], 0.004)


class ArmTests(unittest.TestCase):
    def test_escalation_arm_only_calls_spark_on_anomaly(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim_study(tmp)
            ledger = Ledger(Path(tmp) / "ledger.json")
            ledger.initialize()
            monitor = ModelClient("glimmer-local", transport=scripted_transport(
                {"status": "healthy", "summary": "fine"}))
            spark = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "test-key-0123456789abcdef"},
                                transport=scripted_transport({"incident": False, "root_cause": "healthy"}))
            evaluate(tmp, ["glimmer_to_spark"], clients={"glimmer": monitor, "spark": spark},
                     ids={"inc-01", "inc-02"}, log=lambda *_: None)
            self.assertEqual(spark.calls, 0)
            self.assertGreater(monitor.calls, 10)

    def test_spark_arm_scored_with_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim_study(tmp)
            answers = json.loads((Path(tmp) / "answers" / "answer_keys.json").read_text())["answers"]
            target = next(a for a in answers if a["root_cause"] == "batch_limit_too_low")
            ledger = Ledger(Path(tmp) / "ledger.json")
            ledger.initialize()
            spark = ModelClient("spark", ledger=ledger, environ={"MODEL_API_KEY": "test-key-0123456789abcdef"},
                                transport=scripted_transport({
                                    "incident": True, "root_cause": "batch_limit_too_low", "confidence": 0.8,
                                    "evidence": ["running pinned at max_num_seqs"],
                                    "actions": [{"type": "set_engine_config", "knob": "max_num_seqs",
                                                 "value": 64}], "explanation": "raise the cap"}))
            evaluate(tmp, ["spark"], clients={"spark": spark}, ids={target["id"]}, log=lambda *_: None)
            row = score_study(tmp)["rows"][0]
            self.assertTrue(row["detected"])
            self.assertTrue(row["diagnosis_correct"])
            self.assertTrue(row["fix_proposed"])
            self.assertFalse(row["harmful"])
            self.assertEqual(row["api_calls"], 1)
            self.assertGreater(row["api_cost_usd"], 0)


class WonderArmTests(unittest.TestCase):
    def test_glimmer_to_wonder_uses_wonder_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim_study(tmp)
            answers = json.loads((Path(tmp) / "answers" / "answer_keys.json").read_text())["answers"]
            target = next(a for a in answers if a["root_cause"] == "batch_limit_too_low")
            ledger = Ledger(Path(tmp) / "ledger.json")
            ledger.initialize()
            monitor = ModelClient("glimmer-local", transport=scripted_transport(
                {"status": "anomaly", "summary": "queue growing"}))
            wonder = ModelClient("wonder", ledger=ledger, environ={"MODEL_API_KEY": "test-key-0123456789abcdef"},
                                 transport=scripted_transport({
                                     "incident": True, "root_cause": "batch_limit_too_low",
                                     "actions": [{"type": "set_engine_config", "knob": "max_num_seqs",
                                                  "value": 64}]}))
            self.assertEqual(wonder.spec["model"], "muse-wonder")
            evaluate(tmp, ["glimmer_to_wonder"], clients={"glimmer": monitor, "wonder": wonder},
                     ids={target["id"]}, log=lambda *_: None)
            row = score_study(tmp)["rows"][0]
            self.assertTrue(row["fix_proposed"])
            self.assertEqual(row["api_calls"], 1)
            self.assertAlmostEqual(row["api_cost_usd"], (1000 * 4 + 200 * 20) / 1e6)


class LiveTests(unittest.TestCase):
    def test_rules_fix_context_limit_and_verify_recovery(self):
        study = copy.deepcopy(STUDY)
        study["capacity_rps"] = 16
        study["prompt_tokens"] = {"medium": [700, 900], "long": [1500, 2000]}
        scenario_list, answers = scenarios.generate(study)
        target = next(a for a in answers if a["root_cause"] == "context_limit_too_small")
        scenario = next(s for s in scenario_list if s["id"] == target["id"])
        # Guarantee context failures before the first checkpoint. The original
        # sparse medium mix put its first oversized arrival at 1.9996s, racing
        # the 2s telemetry sample and allowing an unrelated low-arrival decision.
        scenario = dict(scenario, duration_s=6, schedule=[
            {**phase, "mix": {"short": 0, "medium": 1, "long": 0}}
            for phase in scenario["schedule"]])
        questions = [f"Question {i}: compute {i} plus {i}." for i in range(300)]
        pools = scenarios.build_prompt_pools(questions, study["prompt_tokens"], 3, per_class=6)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_live(scenario, 0, arm="rules", clients={}, pools=pools, run_dir=Path(tmp) / "run",
                              serving={"model_id": "fake/fake", "model_revision": "0" * 40, "port": 8000},
                              engine_factory=lambda c, p, d: FakeServer(c, p, d),
                              profile={"arrivals_rps": 8, "prompt_tokens_mean": 150, "gen_tokens_per_s": 50},
                              reference_config=study["engine_base"], checkpoint_s=3,
                              recovery_window_s=4, verify_s=7, lag_s=1, extra_s=12, log=lambda *_: None)
            self.assertEqual(result["decision"]["root_cause"], "context_limit_too_small")
            self.assertEqual(result["executed"][0]["status"], "executed")
            self.assertEqual(result["engine_restarts"][0]["knob"], "max_model_len")
            self.assertTrue(result["recovered"])
            self.assertTrue((Path(tmp) / "run" / "live_result.json").exists())


if __name__ == "__main__":
    unittest.main()
