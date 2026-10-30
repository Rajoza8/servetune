import unittest

from servetune.deadline import SessionDeadline, TimeBudgetExceeded


class DeadlineTests(unittest.TestCase):
    def test_no_work_starts_in_cleanup_reserve(self):
        now = [0]
        deadline = SessionDeadline(100, clock=lambda: now[0])
        self.assertEqual(deadline.timeout(120), 70)
        now[0] = 65
        self.assertEqual(deadline.remaining(), 5)
        with self.assertRaises(TimeBudgetExceeded):
            deadline.require(6)
        now[0] = 70
        with self.assertRaises(TimeBudgetExceeded):
            deadline.timeout(1)

    def test_rejects_nonfinite_and_unusable_limits(self):
        for value in (float("nan"), 0, 30, -1, 50 * 3600 + 1, True):
            with self.assertRaises(ValueError):
                SessionDeadline(value)


if __name__ == "__main__":
    unittest.main()
