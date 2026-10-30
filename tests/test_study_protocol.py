from copy import deepcopy
import random
import math
import unittest

from servetune.study_protocol import (DEFAULT_STUDY, acceptance, apply_proposal,
                                     random_proposal, summarize_repeats,
                                     validate_knobs, validate_study)


CURRENT = {"max_num_seqs": 256, "max_num_batched_tokens": 2048,
           "enable_chunked_prefill": True, "gpu_memory_utilization": .9}


def run(jpt=100, *, jpr=100, tokens=100, p95=10, trace="frozen-trace"):
    return {"status": "pass", "all_requests_completed": True, "joules_per_output_token": jpt,
            "joules_per_completed_request": jpr, "p95_latency_s": p95,
            "generated_tokens": tokens, "completed_requests": 10, "joules": 1000,
            "duration_s": 480, "output_tokens_per_second": tokens / 480,
            "trace_sha256": trace}


class StudyProtocolTests(unittest.TestCase):
    def test_frozen_default_protocol_and_space(self):
        value = validate_study(deepcopy(DEFAULT_STUDY))
        self.assertEqual(value["map"]["repeats"], 3)
        self.assertEqual(value["confirmation"]["repeats"], 5)
        self.assertEqual(value["tuning"]["arm_budget_s"], 21600)
        self.assertEqual(value["map"]["max_num_seqs"], [64])
        value["space"]["max_num_seqs"].append(3)
        self.assertNotIn(3, DEFAULT_STUDY["space"]["max_num_seqs"])

    def test_invalid_protocol_fields_and_types_fail_before_execution(self):
        mutations = [("map", "repeats", 1), ("confirmation", "repeats", 3),
                     ("tuning", "slo_s", float("nan")), ("tuning", "max_trials", True),
                     ("workload", "max_output_tokens", 100000),
                     ("calibration", "rates", [.5, .1]), ("map", "load_fractions", [.5, 1.0])]
        for section, key, value in mutations:
            with self.subTest(key=key):
                config = deepcopy(DEFAULT_STUDY)
                config[section][key] = value
                with self.assertRaises(ValueError):
                    validate_study(config)

    def test_knob_whitelist_prevents_shell_values_bool_int_confusion_and_nan(self):
        for key, value in (("max_num_seqs", True), ("max_num_seqs", 257),
                           ("gpu_memory_utilization", float("nan")),
                           ("enable_chunked_prefill", 1), ("max_num_batched_tokens", "8192; rm")):
            knobs = dict(CURRENT, **{key: value})
            with self.assertRaises(ValueError):
                validate_knobs(knobs, DEFAULT_STUDY["space"])
        with self.assertRaises(ValueError):
            validate_knobs(dict(CURRENT, shell="command"), DEFAULT_STUDY["space"])

    def test_deployed_vllm_defaults_fit_the_predeclared_space(self):
        defaults = dict(CURRENT, max_num_seqs=1024, max_num_batched_tokens=8192,
                        gpu_memory_utilization=.92)
        self.assertEqual(validate_knobs(defaults, DEFAULT_STUDY["space"]), defaults)
        self.assertIn(512, DEFAULT_STUDY["space"]["max_num_seqs"])

    def test_spark_changes_exactly_one_value_from_current_not_fixed_preflight_baseline(self):
        proposal = {"hypothesis": "Test scheduling", "expected_effect": "Unmeasured",
                    "diff": {"max_num_seqs": 128}}
        updated = apply_proposal(CURRENT, proposal, DEFAULT_STUDY["space"])
        self.assertEqual(updated["max_num_seqs"], 128)
        self.assertEqual(CURRENT["max_num_seqs"], 256)
        for diff in ({"max_num_seqs": 256}, {"max_num_seqs": 128, "gpu_memory_utilization": .8},
                     {"shell": "command"}, {"max_num_seqs": 7}):
            with self.assertRaises(ValueError):
                apply_proposal(CURRENT, dict(proposal, diff=diff), DEFAULT_STUDY["space"])

    def test_random_samples_full_space_rather_than_single_knob_neighborhood(self):
        class EnumerateIndex:
            def __init__(self, index): self.index = index
            def randrange(self, size):
                self.size = size
                return self.index
        seen, multi = set(), False
        alternatives = math.prod(len(values) for values in DEFAULT_STUDY["space"].values()) - 1
        for index in range(alternatives):
            proposal = random_proposal(CURRENT, DEFAULT_STUDY["space"], EnumerateIndex(index))
            config = proposal["config"]
            self.assertNotEqual(config, CURRENT)
            validate_knobs(config, DEFAULT_STUDY["space"])
            seen.add(tuple(config.values()))
            multi |= len(proposal["diff"]) > 1
        self.assertEqual(len(seen), alternatives)
        self.assertTrue(multi)
        self.assertEqual(random_proposal(CURRENT, DEFAULT_STUDY["space"], random.Random(42)),
                         random_proposal(CURRENT, DEFAULT_STUDY["space"], random.Random(42)))

    def test_summary_requires_all_repeats_and_never_drops_failure(self):
        summary = summarize_repeats([run(90), run(100), run(110)])
        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["joules_per_output_token"], 100)
        self.assertAlmostEqual(summary["joules_per_token_cv"], .1)
        self.assertEqual(summarize_repeats([run(), run()])["status"], "fail")
        broken = run(); broken["status"] = "fail"
        self.assertEqual(summarize_repeats([run(), broken, run()])["status"], "fail")
        self.assertEqual(summarize_repeats([run()] * 5, expected_repeats=5)["status"], "pass")
        self.assertEqual(summarize_repeats([run(trace="other"), run(), run()])["status"], "fail")

    def test_common_acceptance_requires_strict_gain_slo_quality_and_completeness(self):
        baseline = summarize_repeats([run()] * 3)
        candidate = summarize_repeats([run(97, jpr=97)] * 3)
        gate = {"passed": True, "wording": "within the predeclared 2-percentage-point tolerance"}
        self.assertTrue(acceptance(candidate, baseline, baseline, gate, slo_s=15, observed_cv=.005)["accepted"])
        exactly_two_percent = summarize_repeats([run(98, jpr=98)] * 3)
        self.assertFalse(acceptance(exactly_two_percent, baseline, baseline, gate, slo_s=15, observed_cv=0)["accepted"])
        self.assertFalse(acceptance(candidate, baseline, baseline, gate, slo_s=15, observed_cv=.02)["accepted"])
        self.assertFalse(acceptance(candidate, baseline, baseline, {"passed": False}, slo_s=15, observed_cv=0)["accepted"])
        too_slow = summarize_repeats([run(90, jpr=90, p95=16)] * 3)
        self.assertFalse(acceptance(too_slow, baseline, baseline, gate, slo_s=15, observed_cv=0)["accepted"])
        incomplete = dict(candidate, all_requests_completed=False)
        self.assertFalse(acceptance(incomplete, baseline, baseline, gate, slo_s=15, observed_cv=0)["accepted"])

    def test_length_drift_uses_same_shared_baseline_not_evolving_incumbent(self):
        baseline = summarize_repeats([run(100, jpr=100, tokens=100)] * 3)
        incumbent = summarize_repeats([run(90, jpr=120, tokens=150)] * 3)
        candidate = summarize_repeats([run(80, jpr=110, tokens=150)] * 3)
        decision = acceptance(candidate, incumbent, baseline, {"passed": True}, slo_s=15, observed_cv=0)
        self.assertFalse(decision["accepted"])
        self.assertEqual(decision["length_drift"]["reference"], "same_shared_baseline")
        self.assertIn("length_drift_without_both_energy_gains", decision["reasons"])
        candidate = summarize_repeats([run(80, jpr=95, tokens=150)] * 3)
        self.assertTrue(acceptance(candidate, incumbent, baseline, {"passed": True}, slo_s=15, observed_cv=0)["accepted"])

    def test_different_trace_cannot_pass_a_large_energy_gain(self):
        baseline = summarize_repeats([run()] * 3)
        candidate = summarize_repeats([run(10, jpr=10, trace="changed")] * 3)
        decision = acceptance(candidate, baseline, baseline, {"passed": True}, slo_s=15, observed_cv=0)
        self.assertFalse(decision["accepted"])
        self.assertIn("frozen_trace_mismatch", decision["reasons"])


if __name__ == "__main__":
    unittest.main()
