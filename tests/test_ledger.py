import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from servetune.ledger import BudgetExceeded, Ledger, LedgerError


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.json"
        self.ledger = Ledger(self.path)
        self.ledger.initialize()

    def test_initial_caps_are_separate_and_cannot_be_reset(self):
        summary = self.ledger.summary()
        self.assertEqual(summary["caps_usd"], {"meta": 15, "baseten": 5})
        self.assertEqual(summary["attempts"], 0)
        self.ledger.reserve("meta", 1)
        with self.assertRaises(LedgerError):
            self.ledger.initialize()
        self.assertEqual(self.ledger.summary()["accounted_usd"]["meta"], 1)

    def test_unknown_or_interrupted_usage_survives_reload(self):
        reservation = self.ledger.reserve("meta", "0.40", {"phase": "P3"})
        self.assertTrue(reservation)
        summary = Ledger(self.path).summary()
        self.assertEqual(summary["accounted_usd"]["meta"], .4)
        self.assertEqual(summary["unreconciled_reservations_usd"]["meta"], .4)

    def test_reservation_is_released_only_after_known_usage(self):
        reservation = self.ledger.reserve("meta", 1)
        self.ledger.settle(reservation, ".025", {"prompt_tokens": 10})
        summary = self.ledger.summary()
        self.assertEqual(summary["accounted_usd"]["meta"], .025)
        self.assertEqual(summary["unreconciled_reservations_usd"]["meta"], 0)
        with self.assertRaises(LedgerError):
            self.ledger.settle(reservation, 0)

    def test_exact_cap_blocks_further_provider_reservations(self):
        self.ledger.reserve("meta", 15)
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("meta", ".0000001")
        self.assertEqual(self.ledger.summary()["attempts"], 1)
        self.assertIn("meta", self.ledger.summary()["exhausted_providers"])

    def test_provider_balances_are_independent(self):
        self.ledger.reserve("meta", 14)
        self.ledger.reserve("baseten", 5)
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("baseten", ".01")
        self.assertEqual(self.ledger.summary()["remaining_usd"]["meta"], 1)

    def test_warns_at_half_cap(self):
        self.ledger.reserve("meta", "7.5")
        self.assertTrue(any("meta" in warning for warning in self.ledger.summary()["warnings"]))

    def test_decimal_reservations_do_not_drift(self):
        for _ in range(50):
            self.ledger.reserve("baseten", ".1")
        self.assertEqual(self.ledger.summary()["remaining_usd"]["baseten"], 0)
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("baseten", ".1")

    def test_overrun_is_retained_and_blocks_all_paid_work(self):
        reservation = self.ledger.reserve("meta", .1)
        with self.assertRaises(BudgetExceeded):
            self.ledger.settle(reservation, ".11")
        self.assertEqual(self.ledger.summary()["accounted_usd"]["meta"], .11)
        self.assertTrue(self.ledger.summary()["blocked"])
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("baseten", .1)

    def test_malformed_amounts_never_mutate_ledger(self):
        for amount in (True, float("nan"), float("inf"), -1, 0, "NaN"):
            with self.subTest(amount=amount):
                with self.assertRaises(LedgerError):
                    self.ledger.reserve("meta", amount)
        self.assertEqual(self.ledger.summary()["attempts"], 0)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(LedgerError):
            self.ledger.reserve("other", 1)

    def test_lock_blocks_competing_reservation(self):
        with self.path.with_name(self.path.name + ".lock").open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(LedgerError):
                Ledger(self.path).reserve("meta", 1)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        self.assertEqual(self.ledger.summary()["attempts"], 0)

    def test_raised_or_changed_caps_fail_closed(self):
        data = json.loads(self.path.read_text())
        data["caps_usd"]["meta"] = "16"
        self.path.write_text(json.dumps(data))
        with self.assertRaises(LedgerError):
            self.ledger.reserve("meta", .01)

    def test_duplicate_json_key_fails_closed(self):
        self.path.write_text('{"project":"servetune","project":"other"}')
        with self.assertRaises(LedgerError):
            self.ledger.reserve("meta", .01)

    def test_missing_ledger_does_not_implicitly_start_allowance(self):
        self.path.unlink()
        with self.assertRaises(LedgerError):
            self.ledger.reserve("meta", 1)

    def test_reconciliation_rejects_invalid_usage_metadata(self):
        reservation = self.ledger.reserve("meta", 1)
        with self.assertRaises(LedgerError):
            self.ledger.settle(reservation, .1, {"tokens": float("nan")})
        self.assertEqual(self.ledger.summary()["accounted_usd"]["meta"], 1)


if __name__ == "__main__":
    unittest.main()
