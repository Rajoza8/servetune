"""GPU-board energy measurement with auditable monotonic timestamps.

The preferred source is NVML's cumulative millijoule counter. Averaged-power
integration is explicitly opt-in, carries no independent-10-Hz claim, and must
be qualified separately by the preflight runner.
"""
from __future__ import annotations

import importlib
import math
import threading
import time


class PowerError(RuntimeError):
    pass


class PowerUnavailable(PowerError):
    pass


def _number(value, name: str, *, integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PowerError(f"Invalid {name} reading")
    if not math.isfinite(value) or value < 0 or (integer and int(value) != value):
        raise PowerError(f"Invalid {name} reading")
    return float(value)


class PowerMeter:
    """Measure a complete workload between ``start`` and ``stop``.

    ``snapshot`` also records an explicit observation, useful for idle/load
    checks. The background sampler records polling/update behavior, rather than
    pretending that each poll supplies an independent measurement. ``_nvml``
    and ``_clock`` are injection hooks for deterministic offline tests.
    """
    def __init__(self, gpu_index=0, allow_power_fallback=False, *,
                 sample_interval_s=0.1, gpu_uuid=None, _nvml=None, _clock=time.monotonic):
        if type(gpu_index) is not int or gpu_index < 0:
            raise ValueError("gpu_index must be a nonnegative integer")
        if type(allow_power_fallback) is not bool:
            raise ValueError("allow_power_fallback must be boolean")
        if gpu_uuid is not None and (type(gpu_uuid) is not str or not gpu_uuid.startswith("GPU-")):
            raise ValueError("gpu_uuid must be a physical NVIDIA GPU UUID")
        if (sample_interval_s is not None and
                (isinstance(sample_interval_s, bool) or not isinstance(sample_interval_s, (int, float))
                 or not math.isfinite(sample_interval_s) or not 0.01 <= sample_interval_s <= 10)):
            raise ValueError("sample_interval_s must be between 0.01 and 10 seconds")
        self.gpu_index, self.allow_power_fallback = gpu_index, allow_power_fallback
        self.requested_gpu_uuid, self.gpu_uuid = gpu_uuid, None
        self.sample_interval_s, self._nvml, self._clock = sample_interval_s, _nvml, _clock
        self.samples = []
        self.method = None
        self._active = False
        self._initialized = False
        self._handle = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = None
        self._thread_error = None

    def start(self):
        if self._active or self.samples:
            raise PowerError("A power meter cannot be restarted or reused")
        try:
            if self._nvml is None:
                self._nvml = importlib.import_module("pynvml")
            self._nvml.nvmlInit()
            self._initialized = True
            self._handle = (self._nvml.nvmlDeviceGetHandleByUUID(self.requested_gpu_uuid)
                            if self.requested_gpu_uuid is not None
                            else self._nvml.nvmlDeviceGetHandleByIndex(self.gpu_index))
            try:
                uuid = self._nvml.nvmlDeviceGetUUID(self._handle)
                self.gpu_uuid = uuid.decode() if isinstance(uuid, bytes) else uuid
                if type(self.gpu_uuid) is not str or not self.gpu_uuid.startswith("GPU-"):
                    raise PowerError("NVML returned an invalid GPU UUID")
            except AttributeError:
                self.gpu_uuid = None
            if self.requested_gpu_uuid is not None and self.gpu_uuid != self.requested_gpu_uuid:
                raise PowerError("NVML handle UUID does not match the selected GPU")
            # Establish support before any measurement claims are made.
            try:
                first_counter = self._nvml.nvmlDeviceGetTotalEnergyConsumption(self._handle)
            except Exception as exc:
                if not self.allow_power_fallback:
                    raise PowerUnavailable("NVML cumulative energy is unavailable; no fallback was enabled") from exc
                _number(self._nvml.nvmlDeviceGetPowerUsage(self._handle), "power")
                self.method = "nvml_averaged_power_trapezoid"
            else:
                # Malformed supported telemetry is a failure, not a reason to
                # silently switch to a different measurement method.
                _number(first_counter, "energy counter", integer=True)
                self.method = "nvml_total_energy_counter"
            self._active = True
            self.snapshot()
            if self.sample_interval_s is not None:
                self._thread = threading.Thread(target=self._sample_loop, name="servetune-power", daemon=True)
                self._thread.start()
            return self
        except (ImportError, OSError) as exc:
            self._cleanup()
            raise PowerUnavailable("Install nvidia-ml-py and run on the NVIDIA GPU host") from exc
        except Exception as exc:
            self._active = False
            self._cleanup()
            if isinstance(exc, PowerError):
                raise
            raise PowerUnavailable(f"NVML initialization failed: {type(exc).__name__}") from exc

    def _sample_loop(self):
        while not self._stop_event.wait(self.sample_interval_s):
            try:
                with self._lock:
                    if self._stop_event.is_set():
                        return
                    self.snapshot()
            except Exception as exc:
                self._thread_error = exc
                self._stop_event.set()
                return

    def snapshot(self):
        with self._lock:
            if not self._active:
                raise PowerError("Start the meter before reading a snapshot")
            if self._thread_error is not None:
                raise PowerError("Background energy sampling failed") from self._thread_error
            now = _number(self._clock(), "monotonic timestamp")
            energy = None
            if self.method == "nvml_total_energy_counter":
                energy = _number(self._nvml.nvmlDeviceGetTotalEnergyConsumption(self._handle),
                                 "energy counter", integer=True)
            try:
                power = _number(self._nvml.nvmlDeviceGetPowerUsage(self._handle), "power") / 1000
                if power > 10000:
                    raise PowerError("Implausible GPU power reading")
            except Exception as exc:
                if self.method == "nvml_averaged_power_trapezoid":
                    raise PowerError("Power integration reading failed") from exc
                power = None
            if self.samples:
                previous = self.samples[-1]
                if now < previous["monotonic_s"]:
                    raise PowerError("Monotonic clock moved backwards")
                if energy is not None and energy < previous["energy_mj"]:
                    raise PowerError("Cumulative energy counter reset or moved backwards")
            sample = {"monotonic_s": now, "energy_mj": energy, "power_w": power,
                      "gpu_uuid": self.gpu_uuid}
            self.samples.append(sample)
            return dict(sample)

    def stop(self):
        if not self._active:
            raise PowerError("Power meter is not active")
        try:
            with self._lock:
                self._stop_event.set()
                self.snapshot()  # Capture the end before waiting on the sampler.
            if self._thread is not None:
                self._thread.join(timeout=2)
                if self._thread.is_alive():
                    raise PowerError("Background energy sampler did not stop")
            with self._lock:
                samples = [dict(sample) for sample in self.samples]
            first, last = samples[0], samples[-1]
            duration = last["monotonic_s"] - first["monotonic_s"]
            if duration <= 0:
                raise PowerError("Energy measurement has no positive elapsed time")
            integrated = None
            if all(sample["power_w"] is not None for sample in samples):
                integrated = sum((right["monotonic_s"] - left["monotonic_s"])
                                 * (left["power_w"] + right["power_w"]) / 2
                                 for left, right in zip(samples, samples[1:]))
            changes = []
            if self.method == "nvml_total_energy_counter":
                joules = (last["energy_mj"] - first["energy_mj"]) / 1000
                changes = [right["energy_mj"] - left["energy_mj"]
                           for left, right in zip(samples, samples[1:])
                           if right["energy_mj"] > left["energy_mj"]]
            else:
                joules = integrated
            if joules is None or not math.isfinite(joules) or joules <= 0:
                raise PowerError("No positive finite GPU energy was observed")
            change_times = [right["monotonic_s"] for left, right in zip(samples, samples[1:])
                            if right["energy_mj"] is not None and right["energy_mj"] != left["energy_mj"]]
            update_intervals = [right - left for left, right in zip(change_times, change_times[1:])]
            return {
                "joules": joules, "duration_s": duration, "method": self.method,
                "gpu_uuid": self.gpu_uuid,
                "label": "GPU energy (NVML)", "samples": samples,
                "counter_unit_mj": 1 if self.method == "nvml_total_energy_counter" else None,
                "observed_min_positive_counter_step_mj": min(changes) if changes else None,
                "observed_update_intervals_s": update_intervals,
                "integrated_power_joules": integrated,
                "counter_power_relative_difference": (
                    abs(joules - integrated) / joules
                    if integrated is not None and self.method == "nvml_total_energy_counter" else None),
                "power_reading_note": "NVML power may be averaged over one second; polls are not independent samples",
                "resolution_note": "Counter steps and update intervals are observed bounds, not a calibrated sensor accuracy guarantee",
            }
        finally:
            self._active = False
            self._stop_event.set()
            if self._thread is not None:
                self._thread.join(timeout=2)
            self._cleanup()

    def _cleanup(self):
        if self._initialized:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._initialized = False

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        if self._active:
            if exc_type is None:
                self.stop()
            else:
                self._stop_event.set()
                if self._thread is not None:
                    self._thread.join(timeout=2)
                self._active = False
                self._cleanup()
