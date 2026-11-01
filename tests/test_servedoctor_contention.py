"""Exercise CUDA's asynchronous timing with a deterministic fake device clock."""
from types import SimpleNamespace
import unittest

from servedoctor.jobs.embedding_batch import run_batch


class Tensor:
    def norm(self):
        return 1

    def div_(self, value):
        return self


class AsyncCuda:
    """CPU launches are cheap; synchronize waits for all queued GPU work."""
    def __init__(self, work_s=.005, enqueue_s=.0001):
        self.now = 0.0
        self.device_end = 0.0
        self.work_s, self.enqueue_s = work_s, enqueue_s
        self.active_s = 0.0
        self.calls = 0
        self.outputs = set()
        self.allocations = 0
        self.torch = SimpleNamespace(matmul=self.matmul, empty_like=self.empty_like,
                                     cuda=SimpleNamespace(synchronize=self.synchronize))

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def empty_like(self, tensor):
        self.allocations += 1
        return Tensor()

    def matmul(self, a, b, *, out):
        self.device_end = max(self.now, self.device_end) + self.work_s
        self.now += self.enqueue_s
        self.active_s += self.work_s
        self.calls += 1
        self.outputs.add(id(out))
        return out

    def synchronize(self):
        self.now = max(self.now, self.device_end)


def old_cpu_enqueue_loop(device, seconds=1, duty=.5, period=.2):
    """Previous algorithm, retained only as a regression counterexample."""
    end = device.clock() + seconds
    while device.clock() < end:
        busy_until = device.clock() + period * duty
        while device.clock() < busy_until:
            device.matmul(Tensor(), Tensor(), out=Tensor())
        device.synchronize()
        device.sleep(period * (1 - duty))


class ContentionDutyTests(unittest.TestCase):
    def test_half_duty_measures_completed_gpu_work_instead_of_enqueue_time(self):
        previous = AsyncCuda()
        old_cpu_enqueue_loop(previous)
        self.assertGreater(previous.active_s / previous.now, .95)
        self.assertGreater(previous.now, 4)

        corrected = AsyncCuda()
        run_batch(corrected.torch, Tensor(), Tensor(), seconds=1, duty=.5, period=.2,
                  clock=corrected.clock, sleeper=corrected.sleep)
        self.assertGreaterEqual(corrected.active_s / corrected.now, .45)
        self.assertLessEqual(corrected.active_s / corrected.now, .55)
        self.assertLessEqual(corrected.now, 1 + corrected.work_s + 1e-9)
        self.assertEqual(corrected.allocations, 1)
        self.assertLessEqual(len(corrected.outputs), 2)

    def test_full_duty_stays_busy_without_building_a_gpu_backlog(self):
        device = AsyncCuda()
        run_batch(device.torch, Tensor(), Tensor(), seconds=1, duty=1, period=.2,
                  clock=device.clock, sleeper=device.sleep)
        self.assertGreater(device.active_s / device.now, .99)
        self.assertLessEqual(device.now, 1 + device.work_s + 1e-9)

    def test_long_iteration_can_overshoot_only_by_one_completed_operation(self):
        device = AsyncCuda(work_s=.3)
        run_batch(device.torch, Tensor(), Tensor(), seconds=.2, duty=.5, period=.2,
                  clock=device.clock, sleeper=device.sleep)
        self.assertEqual(device.calls, 1)
        self.assertAlmostEqual(device.now, .3)

    def test_last_sleep_is_clipped_to_run_deadline(self):
        device = AsyncCuda()
        run_batch(device.torch, Tensor(), Tensor(), seconds=.13, duty=.5, period=.2,
                  clock=device.clock, sleeper=device.sleep)
        self.assertAlmostEqual(device.now, .13)


if __name__ == "__main__":
    unittest.main()
