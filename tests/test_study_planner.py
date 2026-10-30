from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from servetune.ledger import Ledger
from servetune.study_planner import propose_spark
from servetune.study_protocol import DEFAULT_STUDY


CURRENT = {"max_num_seqs": 256, "max_num_batched_tokens": 2048,
           "enable_chunked_prefill": True, "gpu_memory_utilization": .9}
GOOD = {"hypothesis": "Test a smaller sequence limit", "expected_effect": "Unmeasured",
        "diff": {"max_num_seqs": 128}}


def response(proposal=GOOD, *, finish="stop", usage=None):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(proposal)}}],
            "usage": usage if usage is not None else {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


class StudyPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger_path = self.root / "ledger.json"
        self.ledger = Ledger(self.ledger_path); self.ledger.initialize()
        self.env = {"MODEL_API_KEY": "test-secret-never-for-artifacts"}
        self.space = deepcopy(DEFAULT_STUDY["space"])
        self.baseline = {"config": CURRENT, "summary": {"status": "pass", "joules_per_output_token": 15.4},
                         "quality_baseline": {"correct": 138, "items": 150, "results": [{"answer": "FINAL-ANSWER-MARKER"}]},
                         "slo_s": 15, "remaining_budget_s": 21000}
        self.out = self.root / "proposal"
        self.calls = 0

    def invoke(self, value, history=None):
        def transport(body, key, timeout):
            self.calls += 1
            self.assertEqual(key, self.env["MODEL_API_KEY"])
            self.assertEqual(body["model"], "muse-spark-1.3")
            self.assertEqual(timeout, 60)
            self.assertEqual(self.ledger.summary()["attempts"], 1)
            self.assertGreater(self.ledger.summary()["unreconciled_reservations_usd"]["meta"], 0)
            return value
        return propose_spark(CURRENT, history or [], self.space, self.baseline, self.ledger_path,
                             self.out, transport=transport, environ=self.env)

    def test_request_uses_current_own_history_and_shared_metrics_then_reserves_before_dispatch(self):
        history = [{"arm": "S", "trial_index": 0, "config": CURRENT,
                    "summary": {"joules_per_output_token": 15.5, "requests": [{"text": "FINAL-ANSWER-MARKER"}]},
                    "decision": {"accepted": False, "reasons": ["insufficient_energy_improvement"]},
                    "other_arm": {"random_winner": "R-WINNER-MARKER"}}]
        result = self.invoke(response(), history)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["next_config"]["max_num_seqs"], 128)
        self.assertEqual(result["history_records"], 1)
        self.assertEqual(self.calls, 1)
        body = json.loads((self.out / "spark-request.json").read_text())
        context = json.loads(body["messages"][1]["content"])
        self.assertEqual(context["current"]["max_num_seqs"], 256)
        self.assertEqual(context["history"][0]["arm"], "S")
        self.assertEqual(context["baseline"]["quality_baseline"], {"correct": 138, "items": 150})
        self.assertNotIn("FINAL-ANSWER-MARKER", json.dumps(body))
        self.assertNotIn("R-WINNER-MARKER", json.dumps(body))
        self.assertEqual(self.ledger.summary()["unreconciled_reservations_usd"]["meta"], 0)

    def test_explicit_other_arm_history_is_rejected_before_dispatch(self):
        with self.assertRaises(ValueError):
            self.invoke(response(), [{"arm": "R", "config": CURRENT}])
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.ledger.summary()["attempts"], 0)

    def test_missing_key_and_exhausted_budget_never_dispatch(self):
        result = propose_spark(CURRENT, [], self.space, self.baseline, self.ledger_path, self.out,
                               transport=lambda *_: self.fail("No call expected"), environ={})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["paid_calls"], 0)
        self.ledger.reserve("meta", 15)
        self.out = self.root / "budget-blocked"
        self.assertEqual(self.invoke(response())["status"], "blocked")
        self.assertEqual(self.calls, 0)

    def test_schema_invalid_or_truncated_response_is_charged_once_without_execution(self):
        for index, value in enumerate((response({"diff": {"shell": "command"}}), response(finish="length"),
                                       response(dict(GOOD, diff={"max_num_seqs": 256})),
                                       response(dict(GOOD, diff={"max_num_seqs": 128, "gpu_memory_utilization": .8})))):
            with self.subTest(index=index):
                self.out = self.root / f"invalid-{index}"
                # Each transport observes this request's durable reservation.
                def transport(*_): return value
                result = propose_spark(CURRENT, [], self.space, self.baseline, self.ledger_path, self.out,
                                       transport=transport, environ=self.env)
                self.assertEqual(result["status"], "fail")
                self.assertIsNone(result["next_config"])
                self.assertEqual(result["paid_calls"], 1)
                self.assertEqual(result["accounting_status"], "usage_reconciled")
        self.assertEqual(self.ledger.summary()["attempts"], 4)
        self.assertEqual(self.ledger.summary()["unreconciled_reservations_usd"]["meta"], 0)

    def test_unknown_usage_and_network_errors_retain_full_reservation(self):
        value = response(); del value["usage"]
        result = self.invoke(value)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["accounting_status"], "full_reservation_retained")
        self.assertEqual(self.ledger.summary()["accounted_usd"]["meta"], result["reserved_usd"])
        self.out = self.root / "network-error"
        def fail(*_): raise urllib.error.URLError(self.env["MODEL_API_KEY"])
        result = propose_spark(CURRENT, [], self.space, self.baseline, self.ledger_path, self.out,
                               transport=fail, environ=self.env)
        self.assertEqual(result["reason"], "URLError")
        self.assertEqual(result["paid_calls"], 1)

    def test_reported_usage_overrun_is_retained_and_blocks_more_calls(self):
        result = self.invoke(response(usage={"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["accounting_status"], "overrun_retained")
        self.assertTrue(self.ledger.summary()["blocked"])

    def test_provider_echoed_key_is_redacted_from_request_response_and_result(self):
        self.baseline["quality_baseline"]["wording"] = self.env["MODEL_API_KEY"]
        proposal = dict(GOOD, hypothesis=self.env["MODEL_API_KEY"])
        self.invoke(response(proposal))
        for path in self.out.glob("*.json"):
            self.assertNotIn(self.env["MODEL_API_KEY"], path.read_text())

    def test_immutable_artifact_directory_prevents_duplicate_paid_call(self):
        self.invoke(response())
        with self.assertRaises(FileExistsError):
            self.invoke(response())
        self.assertEqual(self.calls, 1)


if __name__ == "__main__":
    unittest.main()
