"""Charge an experiment arm only for its allocated wall-clock intervals.

Keep the clock active during model loading, warmup, planning, quality checks,
measurement, failures, and cleanup. Pause it while another arm owns the GPU.
Costs never roll back when a trial fails or its unfinished result is discarded.
"""

from __future__ import annotations

import math
import time
from typing import Callable


def _seconds(value: float, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number of seconds")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be {'positive' if positive else 'nonnegative'}")
    return value


class ArmClock:
    """A monotonic, pausable clock for one arm's complete allocated time.

    An arm must not start another trial unless ``can_start`` accepts the full
    conservative estimate for that trial. The clock retains overruns rather
    than truncating them to the configured budget.
    """

    def __init__(self, budget_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.budget_seconds = _seconds(budget_seconds, "budget_seconds", positive=True)
        self._clock = clock
        self._segments: list[dict] = []
        self._active_start: float | None = None
        self._active_phase: str | None = None
        self._last_read: float | None = None

    def _now(self) -> float:
        value = _seconds(self._clock(), "monotonic clock")
        if self._last_read is not None and value < self._last_read:
            raise ValueError("Monotonic clock moved backwards")
        self._last_read = value
        return value

    @property
    def running(self) -> bool:
        return self._active_start is not None

    def start(self, phase: str = "allocated") -> None:
        if self.running:
            raise ValueError("Arm clock is already running")
        if not isinstance(phase, str) or not phase.strip():
            raise ValueError("phase must be a nonempty string")
        self._active_start = self._now()
        self._active_phase = phase

    def pause(self) -> None:
        if not self.running:
            raise ValueError("Arm clock is not running")
        end = self._now()
        self._segments.append({
            "phase": self._active_phase,
            "started_monotonic_s": self._active_start,
            "ended_monotonic_s": end,
            "seconds": end - self._active_start,
        })
        self._active_start = None
        self._active_phase = None

    @property
    def elapsed_seconds(self) -> float:
        total = sum(segment["seconds"] for segment in self._segments)
        if self.running:
            total += self._now() - self._active_start
        return total

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.budget_seconds - self.elapsed_seconds)

    def can_start(self, estimated_seconds: float) -> bool:
        estimate = _seconds(estimated_seconds, "estimated_seconds", positive=True)
        return estimate <= self.remaining_seconds

    def snapshot(self) -> dict:
        segments = [dict(segment) for segment in self._segments]
        if self.running:
            end = self._now()
            segments.append({
                "phase": self._active_phase,
                "started_monotonic_s": self._active_start,
                "ended_monotonic_s": None,
                "observed_through_monotonic_s": end,
                "seconds": end - self._active_start,
            })
        elapsed = sum(segment["seconds"] for segment in segments)
        return {
            "budget_seconds": self.budget_seconds,
            "elapsed_seconds": elapsed,
            "remaining_seconds": max(0.0, self.budget_seconds - elapsed),
            "over_budget": elapsed > self.budget_seconds,
            "running": self.running,
            "accounting": "sum_of_allocated_wall_clock_intervals",
            "includes": ["planner_wait", "model_load", "warmup", "measurement",
                         "quality_checks", "failures", "reverts", "cleanup"],
            "segments": segments,
        }
