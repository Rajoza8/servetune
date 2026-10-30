import subprocess
import unittest
from unittest.mock import patch

from servetune.hardware import probe_hardware


class HardwareTests(unittest.TestCase):
    @patch("servetune.hardware.shutil.which", return_value=None)
    def test_missing_driver_is_blocked(self, _):
        result = probe_hardware()
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["gpu"])
        self.assertTrue(result["blockers"])

    @patch("servetune.hardware._version", return_value="0.test")
    @patch("servetune.hardware.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch("servetune.hardware.subprocess.run")
    def test_identifies_gpu_without_mutating_it(self, run, *_):
        run.side_effect = [subprocess.CompletedProcess([], 0,
            "0, GPU-123, NVIDIA RTX PRO 6000 Blackwell Workstation Edition, 580.1, 97887, 0, 12.0\n", ""),
            subprocess.CompletedProcess([], 0, "", "")]
        result = probe_hardware()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["gpu"]["uuid"], "GPU-123")
        self.assertEqual(result["driver_version"], "580.1")
        self.assertEqual(len(result["commands"]), 2)
        self.assertFalse(any("shell" in call.kwargs for call in run.call_args_list))
        self.assertTrue(all(any(arg.startswith("--query-") for arg in call.args[0])
                            for call in run.call_args_list))

    @patch("servetune.hardware._version", return_value="0.test")
    @patch("servetune.hardware.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch("servetune.hardware.subprocess.run")
    def test_foreign_compute_process_blocks_exclusivity(self, run, *_):
        run.side_effect = [subprocess.CompletedProcess([], 0,
            "0, GPU-123, NVIDIA RTX PRO 6000 Blackwell, 580.1, 97887, 10, 12.0\n", ""),
            subprocess.CompletedProcess([], 0, "123, python, 10, GPU-123\n", "")]
        result = probe_hardware()
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["processes"][0]["pid"], 123)

    @patch("servetune.hardware._version", return_value="0.test")
    @patch("servetune.hardware.shutil.which", return_value="/usr/bin/nvidia-smi")
    @patch("servetune.hardware.subprocess.run")
    def test_different_gpu_is_not_claimed_as_target(self, run, *_):
        run.side_effect = [subprocess.CompletedProcess([], 0,
            "0, GPU-123, NVIDIA A100, 580.1, 40960, 0, 8.0\n", ""),
            subprocess.CompletedProcess([], 0, "", "")]
        result = probe_hardware()
        self.assertEqual(result["status"], "fail")
        self.assertGreaterEqual(len(result["blockers"]), 2)

    def test_invalid_index_never_executes(self):
        for index in (-1, True, "0"):
            with self.assertRaises(ValueError):
                probe_hardware(index)
