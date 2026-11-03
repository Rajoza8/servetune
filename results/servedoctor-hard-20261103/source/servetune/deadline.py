"""A per-session GPU allocation bound, with time reserved for cleanup."""

import math
import time


class TimeBudgetExceeded(TimeoutError):
    pass


class SessionDeadline:
    def __init__(self, seconds=None, *, clock=time.monotonic, cleanup_seconds=30):
        if seconds is not None and (type(seconds) not in (int, float) or not math.isfinite(seconds)
                                    or seconds <= cleanup_seconds or seconds > 50 * 3600):
            raise ValueError("Session budget must exceed 30 seconds and be at most 50 hours")
        self.clock = clock
        self.started = clock()
        self.seconds = seconds
        self.cleanup_seconds = cleanup_seconds

    def require(self, seconds=1):
        remaining = self.remaining()
        if remaining < seconds:
            raise TimeBudgetExceeded("Insufficient allocated time for the next phase; cleanup is reserved")
        return remaining

    def remaining(self):
        if self.seconds is None:
            return float("inf")
        return max(0, self.seconds - self.cleanup_seconds - (self.clock() - self.started))

    def timeout(self, configured):
        return min(configured, self.require())
