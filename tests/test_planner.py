import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from servetune.ledger import Ledger
from servetune.planner import ProposalError, run_spark_check, validate_proposal


GOOD = {"hypothesis": "A lower batch limit may reduce queueing", "expected_effect": "Unmeasured",
        "diff": {"max_num_seqs": 32}}


def response(proposal=GOOD, *, finish="stop", usage=None):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(proposal)}}],
            "usage": usage if usage is not None else
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger_path = self.root / "ledger.json"
        self.ledger = Ledger(self.ledger_path)
        self.ledger.initialize()
        self.out = self.root / "spark"
        self.env = {"MODEL_API_KEY": "test-secret-not-for-artifacts"}
        self.calls = 0

    def run_response(self, value):
        prior_attempts = self.ledger.summary()["attempts"] if self.ledger_path.exists() else 0
        def transport(body, key, timeout):
            self.calls += 1
            self.assertEqual(key, self.env["MODEL_API_KEY"])
            self.assertEqual(body["model"], "muse-spark-1.3")
            self.assertLessEqual(body["max_completion_tokens"], 2048)
            self.assertEqual(self.ledger.summary()["attempts"], prior_attempts + 1)
            self.assertGreater(self.ledger.summary()["unreconciled_reservations_usd"]["meta"], 0)
            return value
        return run_spark_check(self.ledger_path, self.out, environ=self.env, transport=transport)

    def test_valid_proposal_is_one_reserved_paid_call(self):
        result = self.run_response(response())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["proposal"], GOOD)
        self.assertAlmostEqual(result["estimated_actual_usd"], .0003375)
        self.assertEqual(self.ledger.summary()["unreconciled_reservations_usd"]["meta"], 0)
        self.assertTrue((self.out / "spark-request.json").is_file())

    def test_reused_artifact_directory_cannot_dispatch_again(self):
        self.run_response(response())
        with self.assertRaises(ProposalError):
            self.run_response(response())
        self.assertEqual(self.calls, 1)

    def test_missing_key_blocks_without_charge(self):
        result = run_spark_check(self.ledger_path, self.out, environ={})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["paid_calls"], 0)
        self.assertEqual(self.ledger.summary()["attempts"], 0)

    def test_missing_ledger_blocks_without_dispatch(self):
        self.ledger_path.unlink()
        result = self.run_response(response())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.calls, 0)

    def test_no_secret_in_any_artifact(self):
        proposal = dict(GOOD, hypothesis=self.env["MODEL_API_KEY"])
        self.run_response(response(proposal))
        for path in self.out.glob("*.json"):
            self.assertNotIn(self.env["MODEL_API_KEY"], path.read_text())

    def test_unknown_usage_retains_full_bound(self):
        payload = response()
        del payload["usage"]
        result = self.run_response(payload)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["accounting_status"], "full_reservation_retained")
        self.assertEqual(self.ledger.summary()["accounted_usd"]["meta"], result["reserved_usd"])
        self.assertEqual(self.calls, 1)

    def test_truncation_is_charged_and_not_retried(self):
        result = self.run_response(response(finish="length"))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["accounting_status"], "usage_reconciled")
        self.assertEqual(self.calls, 1)
        self.assertGreater(result["estimated_actual_usd"], 0)

    def test_schema_invalid_answer_still_costs_reported_usage(self):
        result = self.run_response(response({"diff": {"shell": "echo unsafe"}}))
        self.assertEqual(result["status"], "fail")
        self.assertGreater(self.ledger.summary()["accounted_usd"]["meta"], 0)
        self.assertEqual(self.calls, 1)

    def test_http_error_retains_reservation_without_error_body(self):
        def fail(body, key, timeout):
            self.calls += 1
            raise urllib.error.URLError("test-secret-not-for-artifacts")
        result = run_spark_check(self.ledger_path, self.out, environ=self.env, transport=fail)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["reason"], "URLError")
        self.assertGreater(self.ledger.summary()["unreconciled_reservations_usd"]["meta"], 0)
        self.assertNotIn(self.env["MODEL_API_KEY"], (self.out / "spark-result.json").read_text())

    def test_budget_exhaustion_does_not_call_transport(self):
        self.ledger.reserve("meta", 15)
        result = self.run_response(response())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.calls, 0)

    def test_bad_usage_is_never_reconciled(self):
        for index, usage in enumerate((
            {"prompt_tokens": True, "completion_tokens": 1},
            {"prompt_tokens": 1, "completion_tokens": -1},
            {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 4},
        )):
            self.out = self.root / f"bad-usage-{index}"
            result = self.run_response(response(usage=usage))
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["accounting_status"], "full_reservation_retained")

    def test_reported_overrun_is_retained_and_blocks_followups(self):
        result = self.run_response(response(usage={"prompt_tokens": 1_000_000,
                                                   "completion_tokens": 1_000_000}))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["accounting_status"], "overrun_retained")
        self.assertTrue(self.ledger.summary()["blocked"])
        self.assertEqual(self.ledger.summary()["accounted_usd"]["meta"], 5.5)

    def test_proposal_whitelist_rejects_unsafe_or_invalid_values(self):
        for diff in ({"shell": "rm"}, {"max_num_seqs": True}, {"max_num_seqs": 0},
                     {"gpu_memory_utilization": float("nan")},
                     {"max_num_seqs": 32, "max_num_batched_tokens": 4096},
                     {"max_num_seqs": 64}):
            with self.subTest(diff=diff):
                with self.assertRaises(ProposalError):
                    validate_proposal(dict(GOOD, diff=diff))


if __name__ == "__main__":
    unittest.main()
