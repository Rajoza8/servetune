"""Offline reuse of P3 must retain protocol, hash and ledger continuity."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from servetune.artifacts import verify
from servetune.cli import main
from servetune.config import DEFAULT
from servetune.ledger import Ledger
from servetune.planner import (ProposalError, attest_spark_evidence,
                              import_spark_evidence, run_spark_check)
from servetune.preflight import run_preflight


class SparkEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger_path = self.root / "ledger.json"
        Ledger(self.ledger_path).initialize()
        self.evidence = self.root / "spark"
        self.proposal = {"hypothesis": "Test bounded proposal", "expected_effect": "Unmeasured",
                         "diff": {"max_num_seqs": 32}}
        self.transport = Mock(return_value={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.proposal)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
        self.result = run_spark_check(self.ledger_path, self.evidence,
            environ={"MODEL_API_KEY": "test-only-no-network"}, transport=self.transport)
        self.assertEqual(self.result["status"], "pass")

    def change_file(self, name, mutate):
        path = self.evidence / name
        value = json.loads(path.read_text())
        mutate(value)
        path.write_text(json.dumps(value))

    def test_imported_check_makes_no_calls_and_preserves_exact_files_and_accounting(self):
        before = self.ledger_path.read_bytes()
        destination = self.root / "imported"
        imported = import_spark_evidence(self.ledger_path, self.evidence, destination)
        self.assertTrue(imported["imported"])
        self.assertEqual(imported["paid_calls_this_run"], 0)
        self.assertEqual(imported["paid_calls"], 1)
        self.assertEqual(imported["import"]["binding_mode"], "captured_after_request")
        self.transport.assert_called_once()
        self.assertEqual(self.ledger_path.read_bytes(), before)
        for name in ("spark-request.json", "spark-usage.json", "spark-result.json"):
            self.assertEqual((destination / name).read_bytes(), (self.evidence / name).read_bytes())

    def test_valid_but_changed_proposal_cannot_reuse_prior_hash_binding(self):
        self.change_file("spark-result.json", lambda result: result["proposal"]["diff"].update(max_num_seqs=16))
        with self.assertRaises(ProposalError):
            import_spark_evidence(self.ledger_path, self.evidence, self.root / "imported")
        with self.assertRaises(ProposalError):
            attest_spark_evidence(self.ledger_path, self.evidence)
        self.assertFalse((self.root / "imported").exists())

    def test_request_must_match_current_fixed_model_and_baseline(self):
        self.change_file("spark-request.json", lambda request: request.update(model="other-model"))
        with self.assertRaises(ProposalError):
            import_spark_evidence(self.ledger_path, self.evidence, self.root / "imported")

    def test_forged_usage_or_cost_is_not_importable(self):
        self.change_file("spark-usage.json", lambda usage: usage["usage"].update(completion_tokens=51))
        with self.assertRaises(ProposalError):
            import_spark_evidence(self.ledger_path, self.evidence, self.root / "imported")

    def test_forged_reservation_cannot_match_another_ledger(self):
        new_ledger = self.root / "new-ledger.json"
        Ledger(new_ledger).initialize()
        with self.assertRaises(ProposalError):
            import_spark_evidence(new_ledger, self.evidence, self.root / "imported")

    def test_ledger_origin_must_remain_identical_after_copying(self):
        data = json.loads(self.ledger_path.read_text())
        data["created_at"] = "a-different-ledger-origin"
        self.ledger_path.write_text(json.dumps(data))
        with self.assertRaises(ProposalError):
            import_spark_evidence(self.ledger_path, self.evidence, self.root / "imported")

    def test_legacy_unbound_evidence_requires_explicit_owner_attestation(self):
        data = json.loads(self.ledger_path.read_text())
        del data["entries"][0]["metadata"]["p3_evidence"]
        self.ledger_path.write_text(json.dumps(data))
        with self.assertRaises(ProposalError):
            import_spark_evidence(self.ledger_path, self.evidence, self.root / "imported")
        binding = attest_spark_evidence(self.ledger_path, self.evidence)
        self.assertEqual(binding["mode"], "explicit_local_attestation")
        imported = import_spark_evidence(self.ledger_path, self.evidence, self.root / "imported")
        self.assertEqual(imported["status"], "pass")
        self.assertEqual(Ledger(self.ledger_path).summary()["attempts"], 1)

    def test_boolean_paid_call_count_is_not_accepted(self):
        self.change_file("spark-result.json", lambda result: result.update(paid_calls=True))
        with self.assertRaises(ProposalError):
            import_spark_evidence(self.ledger_path, self.evidence, self.root / "imported")

    def test_nonfinite_or_missing_reported_cost_is_rejected_cleanly(self):
        self.change_file("spark-usage.json", lambda usage: usage.update(estimated_cost_usd="NaN"))
        with self.assertRaises(ProposalError):
            import_spark_evidence(self.ledger_path, self.evidence, self.root / "imported")

    def test_symlink_evidence_and_existing_destinations_are_rejected(self):
        linked = self.root / "linked"
        linked.symlink_to(self.evidence, target_is_directory=True)
        with self.assertRaises(ProposalError):
            import_spark_evidence(self.ledger_path, linked, self.root / "imported")
        destination = self.root / "already-exists"
        destination.mkdir()
        with self.assertRaises(FileExistsError):
            import_spark_evidence(self.ledger_path, self.evidence, destination)

    def test_preflight_finalization_imports_verified_check_and_seals_without_rebilling(self):
        def passed_local_gates(config, root, result, event, deadline, *, dev_baseline_evidence=None):
            self.assertIsNone(dev_baseline_evidence)
            for name in ("P1", "P2", "P4", "quality_baseline"):
                result["checks"][name] = {"status": "pass", "reason": "Offline integration fixture"}
        output = self.root / "preflight"
        before = Ledger(self.ledger_path).summary()
        with patch("servetune.preflight._live", side_effect=passed_local_gates), \
             patch("servetune.planner.run_spark_check", side_effect=AssertionError("No second API call")), \
             redirect_stdout(StringIO()):
            result = run_preflight(deepcopy(DEFAULT), output, ledger_path=self.ledger_path,
                                   spark_evidence=self.evidence)
        self.assertTrue(result["live_preflight_passed"])
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["paid_calls_this_run"], 0)
        self.assertTrue(result["checks"]["P3"]["imported"])
        self.assertEqual(Ledger(self.ledger_path).summary(), before)
        self.assertEqual(verify(output), result)

    def test_forged_import_fails_p3_even_when_local_gates_pass(self):
        def passed_local_gates(config, root, result, event, deadline, *, dev_baseline_evidence=None):
            self.assertIsNone(dev_baseline_evidence)
            for name in ("P1", "P2", "P4", "quality_baseline"):
                result["checks"][name] = {"status": "pass", "reason": "Offline integration fixture"}
        self.change_file("spark-result.json", lambda result: result.update(reservation_id="forged"))
        output = self.root / "preflight"
        with patch("servetune.preflight._live", side_effect=passed_local_gates), redirect_stdout(StringIO()):
            result = run_preflight(deepcopy(DEFAULT), output, ledger_path=self.ledger_path,
                                   spark_evidence=self.evidence)
        self.assertFalse(result["live_preflight_passed"])
        self.assertEqual(result["checks"]["P3"]["status"], "fail")
        self.assertEqual(result["paid_calls_this_run"], 0)
        self.assertEqual(verify(output), result)

    def test_conflicting_paid_and_reused_modes_fail_before_output_creation(self):
        with self.assertRaises(ValueError):
            run_preflight(deepcopy(DEFAULT), self.root / "preflight", with_spark=True,
                          spark_evidence=self.evidence)
        self.assertFalse((self.root / "preflight").exists())
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(["preflight", "--out", str(self.root / "cli"),
                      "--with-spark", "--spark-evidence", str(self.evidence)])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
