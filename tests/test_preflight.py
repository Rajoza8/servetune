from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from servetune.artifacts import verify
from servetune.config import DEFAULT, validate
from servetune.preflight import render_report, run_preflight


class PreflightTests(unittest.TestCase):
    def test_simulation_never_touches_hardware_network_or_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "simulation"
            with patch("servetune.preflight.ManagedEngine", side_effect=AssertionError("GPU touched")), \
                 patch("servetune.preflight.PowerMeter", side_effect=AssertionError("NVML touched")), \
                 patch("servetune.planner.run_spark_check", side_effect=AssertionError("Paid API touched")), \
                 redirect_stdout(StringIO()):
                result = run_preflight(deepcopy(DEFAULT), directory, simulate=True, with_spark=True)
            self.assertEqual(result["status"], "simulation_complete")
            self.assertFalse(result["live_preflight_passed"])
            self.assertFalse(result["measurement_prerequisites_passed"])
            self.assertEqual(result["paid_calls_this_run"], 0)
            self.assertEqual(verify(directory), result)
            (directory / "fixture-1.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify(directory)

    def test_no_gpu_blocks_before_any_model_or_paid_operation(self):
        hardware = {"status": "blocked", "blockers": ["No NVIDIA GPU"]}
        with tempfile.TemporaryDirectory() as temporary, \
             patch("servetune.preflight.probe_hardware", return_value=hardware), \
             patch("servetune.preflight.ManagedEngine", side_effect=AssertionError("GPU touched")), \
             patch("servetune.planner.run_spark_check", side_effect=AssertionError("Paid API touched")), \
             redirect_stdout(StringIO()):
            directory = Path(temporary) / "blocked"
            result = run_preflight(deepcopy(DEFAULT), directory, with_spark=True)
            self.assertEqual(result["checks"]["P1"]["status"], "blocked")
            self.assertEqual(result["checks"]["P3"]["status"], "skipped")
            self.assertFalse(result["live_preflight_passed"])
            self.assertEqual(verify(directory), result)

    def test_evidence_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            directory = Path(temporary) / "simulation"
            run_preflight(deepcopy(DEFAULT), directory, simulate=True)
            with self.assertRaises(FileExistsError):
                run_preflight(deepcopy(DEFAULT), directory, simulate=True)

    def test_simulation_refuses_importing_live_quality_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "simulation"
            with self.assertRaises(ValueError):
                run_preflight(deepcopy(DEFAULT), directory, simulate=True,
                              dev_baseline_evidence=Path("sealed-live-reference"))
            self.assertFalse(directory.exists())

    def test_paid_success_without_reason_can_render(self):
        result = {"mode": "live", "status": "pass", "checks": {"P3": {"status": "pass", "paid_calls": 1}},
                  "live_preflight_passed": True, "measurement_prerequisites_passed": True}
        self.assertIn("P3", render_report(result))

    def test_config_rejects_cap_raise_shell_flags_and_wrong_noise_protocol(self):
        for section, key, value in (("provider_caps_usd", "meta", 16), ("engine", "engine_executable", "sh"),
                                    ("measurement", "repeats", 1), ("trace", "duration_s", 1)):
            config = deepcopy(DEFAULT)
            config[section][key] = value
            with self.assertRaises(ValueError):
                validate(config)


if __name__ == "__main__":
    unittest.main()
