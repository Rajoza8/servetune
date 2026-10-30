"""Exercise the live orchestration with local fakes, never GPU/API evidence."""

from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from servetune.artifacts import verify, write_json
from servetune.config import DEFAULT
from servetune.power import PowerError
from servetune.preflight import run_preflight
from servetune.quality import score_items


UUID = "GPU-11111111-2222-3333-4444-555555555555"


def measurement(factor=1.0, *, gpu_uuid=UUID):
    # 500 genuine counter increments over a 120-second fake window, with a
    # consistent 100 W energy delta. Fakes preserve enough telemetry detail to
    # exercise the real boundary-granularity and idle/load gates.
    increment_mj = int(24_000 * factor)
    energy_j = increment_mj * 500 / 1000
    energy = {"method": "nvml_total_energy_counter", "duration_s": 120.0,
              "gpu_uuid": gpu_uuid, "joules": energy_j,
              "samples": [{"monotonic_s": index * .24,
                           "energy_mj": 1_000_000 + index * increment_mj,
                           "power_w": energy_j / 120}
                          for index in range(501)],
              "observed_update_intervals_s": [.24] * 499}
    return {"status": "pass", "all_requests_completed": True,
            "completed_requests": 12, "scheduled_requests": 12,
            "generated_tokens": 1000, "prompt_tokens": 120,
            "energy": energy, "joules": energy_j,
            "joules_per_output_token": energy_j / 1000,
            "joules_per_completed_request": energy_j / 12,
            "p95_latency_s": .5 * factor,
            "output_tokens_per_second": 1000 / 120}


class LiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = deepcopy(DEFAULT)
        self.config["engine"]["model_revision"] = "a" * 40
        self.config["engine"]["use_engine_defaults"] = True
        self.dev = [{"id": f"dev-{i}", "prompt": f"Question {i}", "answer": "42"}
                    for i in range(150)]
        self.baseline = score_items(self.dev,
            [{"id": row["id"], "text": "#### 42", "finish_reason": "stop"}
             for row in self.dev])
        self.dtypes = []
        self.fail_fp8 = False
        self.fail_second_bf16 = False
        self.idle_error = None

    def execute(self, *, factors=(1, 1.005, .995), measurements=None,
                baseline=None, spark=None, with_spark=True,
                baseline_evidence=None, baseline_import_error=None):
        owner = self

        class FakeEngine:
            def __init__(self, config, artifact_dir, dtype):
                owner.assertEqual(config["gpu_uuid"], UUID)
                owner.assertTrue(config["use_engine_defaults"])
                self.artifact_dir = Path(artifact_dir)
                self.dtype = dtype
                self.base_url = "http://127.0.0.1:8000/v1"
                self.metadata = {"identity_complete": True, "dtype": dtype,
                                 "gpu_uuid": UUID, "vllm_version": "fake-for-tests-only"}
                owner.dtypes.append(dtype)

            def __enter__(self):
                self.artifact_dir.mkdir(parents=True, exist_ok=True)
                if self.dtype == "bf16" and owner.fail_second_bf16 and owner.dtypes.count("bf16") == 2:
                    raise RuntimeError("Fake TIME_WAIT restart guard failure")
                if self.dtype == "fp8" and owner.fail_fp8:
                    raise RuntimeError("Fake FP8 kernel failure")
                return self

            def __exit__(self, *args):
                return False

        class FakePower:
            def __init__(self, gpu_index=0, allow_power_fallback=False, *, gpu_uuid=None):
                owner.assertEqual(gpu_index, 0)
                owner.assertEqual(gpu_uuid, UUID)

            def start(self):
                if owner.idle_error:
                    raise owner.idle_error
                return self

            def stop(self):
                return {"method": "nvml_total_energy_counter", "duration_s": 3,
                        "gpu_uuid": UUID, "joules": 30,
                        "samples": [{"monotonic_s": 0, "energy_mj": 1_000_000},
                                    {"monotonic_s": 3, "energy_mj": 1_030_000}]}

        hardware = {"status": "pass", "blockers": [], "gpu": {"uuid": UUID},
                    "driver_version": "fake-test-driver"}
        smoke = {"text": "ready", "finish_reason": "stop",
                 "usage": {"prompt_tokens": 10, "completion_tokens": 1}}
        fake_spark = spark if spark is not None else {"check": "P3", "status": "pass", "paid_calls": 1}
        trials = measurements if measurements is not None else [measurement(f) for f in factors]
        output = self.root / "run"
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(StringIO()))
            stack.enter_context(patch("servetune.preflight.probe_hardware", return_value=hardware))
            stack.enter_context(patch("servetune.preflight.ManagedEngine", FakeEngine))
            stack.enter_context(patch("servetune.preflight.PowerMeter", FakePower))
            stack.enter_context(patch("servetune.preflight.time.sleep"))
            stack.enter_context(patch("servetune.preflight._load_data",
                return_value=(["Performance-only calibration prompt"], self.dev,
                              {"test_fixture": "local fake manifest"})))
            completion_call = stack.enter_context(patch("servetune.preflight.completion", return_value=smoke))
            run_trace_call = stack.enter_context(patch("servetune.preflight.run_trace", side_effect=trials))
            baseline_call = stack.enter_context(patch("servetune.preflight._quality_baseline",
                return_value=deepcopy(self.baseline if baseline is None else baseline)))
            spark_call = stack.enter_context(patch("servetune.planner.run_spark_check", return_value=fake_spark))
            def import_reference(source, destination, **arguments):
                if baseline_import_error:
                    raise baseline_import_error
                owner.assertEqual(source, baseline_evidence)
                owner.assertEqual(arguments["dev_items"], owner.dev)
                destination.mkdir()
                origin = {"source_manifest_sha256": "test-original-seal", "correct": owner.baseline["correct"]}
                write_json(destination / "origin.json", origin)
                return {"baseline": deepcopy(owner.baseline), "origin": origin,
                        "baseline_bytes": json.dumps(owner.baseline).encode()}
            imported = stack.enter_context(patch("servetune.evidence.import_dev_baseline", side_effect=import_reference))
            result = run_preflight(self.config, output, with_spark=with_spark,
                                   ledger_path=self.root / "unopened-fake-ledger.json",
                                   dev_baseline_evidence=baseline_evidence)
        # Every path, including gate failures, must finish and seal its evidence.
        self.assertEqual(verify(output), result)
        self.assertFalse((self.root / "unopened-fake-ledger.json").exists())
        return result, {"spark": spark_call, "baseline": baseline_call,
                        "completion": completion_call, "trace": run_trace_call,
                        "imported": imported}, output

    def test_successful_live_orchestration_passes_and_seals_without_p3_reason(self):
        result, calls, output = self.execute()
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["live_preflight_passed"])
        self.assertTrue(result["measurement_prerequisites_passed"])
        self.assertFalse(result["floor_built"])
        self.assertTrue(all(gate["status"] == "pass" for gate in result["checks"].values()))
        self.assertEqual(result["paid_calls_this_run"], 1)
        # Fake P3 did not create a request file: accounting must come from its
        # authoritative dispatch field rather than filesystem existence.
        self.assertFalse((output / "spark" / "spark-request.json").exists())
        self.assertEqual(calls["trace"].call_count, 3)
        calls["spark"].assert_called_once()
        calls["baseline"].assert_called_once()
        self.assertEqual(len(calls["baseline"].call_args.args[1]), 150)
        self.assertEqual(self.dtypes, ["bf16", "bf16", "bf16", "fp8"])
        self.assertIn("Check completed", (output / "preflight.md").read_text())

    def test_failed_baseline_request_blocks_overall_pass(self):
        outputs = [{"id": row["id"], "text": "#### 42", "finish_reason": "stop"}
                   for row in self.dev]
        outputs[0] = {"id": self.dev[0]["id"], "text": "", "error": "TimeoutError"}
        baseline = score_items(self.dev, outputs)
        self.assertEqual(baseline["failed_requests"], 1)
        result, calls, _ = self.execute(baseline=baseline)
        self.assertEqual(result["checks"]["quality_baseline"]["status"], "fail")
        self.assertFalse(result["live_preflight_passed"])
        self.assertNotEqual(result["status"], "pass")
        self.assertTrue(result["measurement_prerequisites_passed"])

    def test_later_bf16_restart_failure_preserves_successful_p1_and_quality_reference(self):
        self.fail_second_bf16 = True
        result, calls, _ = self.execute()
        self.assertEqual(result["checks"]["P1"]["status"], "pass")
        self.assertEqual(result["checks"]["P4"]["status"], "fail")
        self.assertEqual(result["checks"]["quality_baseline"]["status"], "pass")
        self.assertFalse(result["measurement_prerequisites_passed"])
        self.assertEqual(calls["trace"].call_count, 1)
        calls["baseline"].assert_called_once()

    def test_verified_reference_import_never_remeasures_quality_but_repeats_all_traces(self):
        outputs = [{"id": row["id"], "text": "#### 41" if i < 12 else "#### 42", "finish_reason": "stop"}
                   for i, row in enumerate(self.dev)]
        self.baseline = score_items(self.dev, outputs)
        result, calls, output = self.execute(baseline_evidence=Path("sealed-original-reference"))
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checks"]["quality_baseline"]["imported"])
        self.assertEqual(result["checks"]["quality_baseline"]["correct"], 138)
        self.assertEqual(json.loads((output / "dev-baseline.json").read_text())["correct"], 138)
        calls["baseline"].assert_not_called()
        calls["imported"].assert_called_once()
        self.assertEqual(calls["trace"].call_count, 3)

    def test_bad_reference_import_stops_before_engine_and_never_replaces_score(self):
        result, calls, output = self.execute(baseline_evidence=Path("bad-original-reference"),
                                            baseline_import_error=ValueError("Changed scorer"))
        self.assertEqual(result["checks"]["quality_baseline"]["status"], "fail")
        self.assertEqual(self.dtypes, [])
        calls["baseline"].assert_not_called()
        calls["trace"].assert_not_called()
        self.assertFalse((output / "dev-baseline.json").exists())

    def test_high_noise_fails_p4_and_does_not_start_optional_fp8_or_spark(self):
        result, calls, _ = self.execute(factors=(1, 1, 1.5))
        self.assertEqual(result["checks"]["P4"]["status"], "fail")
        self.assertFalse(result["measurement_prerequisites_passed"])
        self.assertFalse(result["live_preflight_passed"])
        self.assertNotIn("fp8", self.dtypes)
        calls["spark"].assert_not_called()

    def test_idle_counter_reset_blocks_telemetry_before_model_start(self):
        self.idle_error = PowerError("Cumulative energy counter reset or moved backwards")
        result, calls, _ = self.execute()
        self.assertEqual(result["checks"]["P2"]["status"], "blocked")
        self.assertFalse(result["measurement_prerequisites_passed"])
        self.assertFalse(result["live_preflight_passed"])
        self.assertEqual(self.dtypes, [])
        calls["trace"].assert_not_called()
        calls["spark"].assert_not_called()

    def test_wrong_gpu_energy_uuid_cannot_pass_measurement_gates(self):
        result, calls, _ = self.execute(measurements=[measurement(gpu_uuid="GPU-other")])
        self.assertFalse(result["measurement_prerequisites_passed"])
        self.assertFalse(result["live_preflight_passed"])
        self.assertEqual(result["checks"]["P1"]["status"], "pass")
        self.assertEqual(result["checks"]["P2"]["status"], "fail")
        self.assertEqual(self.dtypes, ["bf16"])
        calls["baseline"].assert_not_called()
        calls["spark"].assert_not_called()

    def test_load_counter_failure_cannot_pass_measurement_gates(self):
        result, calls, _ = self.execute(measurements=[PowerError("Counter reset during trace")])
        self.assertFalse(result["measurement_prerequisites_passed"])
        self.assertFalse(result["live_preflight_passed"])
        self.assertEqual(result["checks"]["P1"]["status"], "pass")
        self.assertEqual(result["checks"]["P2"]["status"], "fail")
        calls["spark"].assert_not_called()

    def test_optional_fp8_failure_preserves_bf16_prerequisites(self):
        self.fail_fp8 = True
        result, calls, _ = self.execute()
        self.assertEqual(result["checks"]["P1b"]["status"], "fail")
        self.assertTrue(result["measurement_prerequisites_passed"])
        self.assertTrue(result["live_preflight_passed"])
        self.assertEqual(result["status"], "pass")
        calls["spark"].assert_called_once()

    def test_missing_spark_key_result_does_not_count_a_paid_call(self):
        result, _, _ = self.execute(spark={"check": "P3", "status": "blocked",
            "reason": "No environment key", "paid_calls": 0})
        self.assertEqual(result["paid_calls_this_run"], 0)
        self.assertFalse(result["live_preflight_passed"])
        self.assertTrue(result["measurement_prerequisites_passed"])

    def test_missing_baseline_failure_count_cannot_default_to_pass(self):
        broken = deepcopy(self.baseline)
        del broken["failed_requests"]
        result, calls, _ = self.execute(baseline=broken)
        self.assertFalse(result["live_preflight_passed"])
        self.assertNotEqual(result["checks"]["quality_baseline"]["status"], "pass")
        calls["spark"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
