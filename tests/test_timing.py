import unittest

from servetune.timing import ArmClock


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ArmClockTests(unittest.TestCase):
    def test_alternating_arms_charge_only_allocated_intervals(self):
        clock = FakeClock()
        random_arm, spark_arm = ArmClock(60, clock), ArmClock(60, clock)
        random_arm.start("trial-1")
        clock.advance(10)
        random_arm.pause()
        spark_arm.start("planner-and-measurement")
        clock.advance(20)
        spark_arm.pause()
        random_arm.start("trial-2")
        clock.advance(5)
        random_arm.pause()
        self.assertEqual(random_arm.elapsed_seconds, 15)
        self.assertEqual(spark_arm.elapsed_seconds, 20)
        self.assertEqual(random_arm.remaining_seconds, 45)

    def test_unfinished_and_failed_trial_costs_do_not_roll_back(self):
        clock = FakeClock()
        arm = ArmClock(10, clock)
        arm.start("failed-oom-trial")
        clock.advance(12)
        snapshot = arm.snapshot()
        self.assertEqual(snapshot["elapsed_seconds"], 12)
        self.assertTrue(snapshot["over_budget"])
        self.assertFalse(arm.can_start(1))
        arm.pause()
        self.assertEqual(arm.elapsed_seconds, 12)
        self.assertEqual(arm.remaining_seconds, 0)

    def test_live_snapshot_is_non_destructive_and_owned(self):
        clock = FakeClock()
        arm = ArmClock(10, clock)
        arm.start("planner_wait")
        clock.advance(2)
        snapshot = arm.snapshot()
        self.assertIsNone(snapshot["segments"][0]["ended_monotonic_s"])
        snapshot["segments"][0]["seconds"] = 999
        clock.advance(1)
        arm.pause()
        self.assertEqual(arm.snapshot()["segments"][0]["seconds"], 3)

    def test_budget_prediction_includes_current_interval(self):
        clock = FakeClock()
        arm = ArmClock(10, clock)
        arm.start()
        clock.advance(7)
        self.assertTrue(arm.can_start(3))
        self.assertFalse(arm.can_start(3.01))

    def test_invalid_state_and_clock(self):
        clock = FakeClock()
        arm = ArmClock(10, clock)
        with self.assertRaises(ValueError):
            arm.pause()
        arm.start()
        with self.assertRaises(ValueError):
            arm.start()
        clock.advance(2)
        self.assertEqual(arm.elapsed_seconds, 2)
        clock.advance(-1)
        with self.assertRaises(ValueError):
            arm.pause()

    def test_numeric_validation(self):
        for value in (True, 0, -1, float("nan"), float("inf"), "60"):
            with self.assertRaises(ValueError):
                ArmClock(value)
        arm = ArmClock(60)
        for value in (True, 0, -1, float("nan"), float("inf"), "1"):
            with self.assertRaises(ValueError):
                arm.can_start(value)


if __name__ == "__main__":
    unittest.main()
