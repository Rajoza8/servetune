import unittest

from servetune.power import PowerError, PowerMeter, PowerUnavailable


class FakeNVML:
    def __init__(self, energies=(0, 1000, 2000), powers=(100000, 100000), supported=True):
        self.energies, self.powers = iter(energies), iter(powers)
        self.supported = supported
        self.shutdown = False

    def nvmlInit(self):
        pass

    def nvmlShutdown(self):
        self.shutdown = True

    def nvmlDeviceGetHandleByIndex(self, index):
        return index

    def nvmlDeviceGetHandleByUUID(self, uuid):
        return 0

    def nvmlDeviceGetUUID(self, handle):
        return "GPU-123"

    def nvmlDeviceGetTotalEnergyConsumption(self, handle):
        if not self.supported:
            raise RuntimeError("not supported")
        return next(self.energies)

    def nvmlDeviceGetPowerUsage(self, handle):
        return next(self.powers)


class PowerTests(unittest.TestCase):
    def meter(self, nvml, times):
        return PowerMeter(_nvml=nvml, _clock=lambda: next(times), sample_interval_s=None)

    def test_counter_is_millijoules_not_watt_samples(self):
        nvml = FakeNVML((0, 1000, 201000), (100000, 100000))
        meter = self.meter(nvml, iter((10, 12)))
        meter.start()
        result = meter.stop()
        self.assertEqual(result["joules"], 200)
        self.assertEqual(result["duration_s"], 2)
        self.assertEqual(result["integrated_power_joules"], 200)
        self.assertEqual(result["counter_power_relative_difference"], 0)
        self.assertTrue(nvml.shutdown)
        self.assertEqual(result["method"], "nvml_total_energy_counter")
        self.assertEqual(result["gpu_uuid"], "GPU-123")
        self.assertTrue(all(sample["gpu_uuid"] == "GPU-123" for sample in result["samples"]))

    def test_uuid_selected_meter_verifies_handle_identity(self):
        nvml = FakeNVML()
        meter = PowerMeter(gpu_uuid="GPU-wrong", _nvml=nvml, sample_interval_s=None)
        with self.assertRaises(PowerError):
            meter.start()
        self.assertTrue(nvml.shutdown)

    def test_records_observed_update_granularity_without_independence_claim(self):
        nvml = FakeNVML((0, 1000, 1000, 2000, 4000), (100000,) * 4)
        meter = self.meter(nvml, iter((10, 10.1, 10.2, 10.3)))
        meter.start()
        meter.snapshot()
        meter.snapshot()
        result = meter.stop()
        self.assertEqual(len(result["samples"]), 4)
        self.assertEqual(result["observed_min_positive_counter_step_mj"], 1000)
        self.assertAlmostEqual(result["observed_update_intervals_s"][0], 0.1)
        self.assertIn("not independent", result["power_reading_note"])

    def test_unsupported_counter_fails_without_explicit_fallback(self):
        nvml = FakeNVML(supported=False)
        with self.assertRaises(PowerUnavailable):
            self.meter(nvml, iter((0, 1))).start()
        self.assertTrue(nvml.shutdown)

    def test_explicit_averaged_power_fallback_is_labelled(self):
        nvml = FakeNVML(powers=(100000, 100000, 200000), supported=False)
        times = iter((0, 2))
        meter = PowerMeter(allow_power_fallback=True, _nvml=nvml,
                           _clock=lambda: next(times), sample_interval_s=None)
        meter.start()
        result = meter.stop()
        self.assertEqual(result["joules"], 300)
        self.assertEqual(result["method"], "nvml_averaged_power_trapezoid")
        self.assertIsNone(result["counter_unit_mj"])

    def test_counter_reset_is_a_measurement_failure(self):
        nvml = FakeNVML((100, 1000, 0), (100000,) * 2)
        meter = self.meter(nvml, iter((0, 1)))
        meter.start()
        with self.assertRaises(PowerError):
            meter.stop()
        self.assertTrue(nvml.shutdown)

    def test_unchanging_counter_is_not_a_zero_energy_success(self):
        nvml = FakeNVML((1000, 1000, 1000), (100000,) * 2)
        meter = self.meter(nvml, iter((0, 1)))
        meter.start()
        with self.assertRaises(PowerError):
            meter.stop()

    def test_backwards_clock_fails(self):
        nvml = FakeNVML((0, 1000, 2000), (100000,) * 2)
        meter = self.meter(nvml, iter((5, 4)))
        meter.start()
        with self.assertRaises(PowerError):
            meter.stop()

    def test_no_reuse_of_measurement_object(self):
        nvml = FakeNVML((0, 1000, 2000), (100000,) * 2)
        meter = self.meter(nvml, iter((0, 1)))
        meter.start()
        meter.stop()
        with self.assertRaises(PowerError):
            meter.start()
