import copy
import unittest

from servetune.quality import (
    TOLERANCE_WORDING, evaluate_gate, extract_answer, normalize_answer,
    score_items, validate_dataset_manifest,
)


def items(count, prefix="dev"):
    return [{"id": f"{prefix}-{i}", "prompt": f"{prefix} question {i}", "answer": "4"}
            for i in range(count)]


def outputs(records, wrong=0):
    return [{"id": item["id"], "text": "#### 5" if index < wrong else "#### 4",
             "finish_reason": "stop"} for index, item in enumerate(records)]


class QualityTests(unittest.TestCase):
    def test_extraction_and_declared_normalization(self):
        self.assertEqual(extract_answer("work\n#### 1.00\n"), "1.00")
        self.assertEqual(extract_answer(r"work \boxed{2} then \boxed{3}"), "3")
        self.assertEqual(extract_answer("reasoning\nFour"), "Four")
        self.assertEqual(normalize_answer("  FOur\tWORDS "), "four words")
        self.assertEqual(normalize_answer("+01.000"), "1")
        self.assertEqual(normalize_answer("-.0"), "0")
        self.assertEqual(normalize_answer("2 + 2"), "2 + 2")
        self.assertNotEqual(normalize_answer("2 + 2"), normalize_answer("4"))

    def test_missing_and_empty_requests_are_incorrect_and_failed(self):
        records = items(3)
        result = score_items(records, [{"id": "dev-0", "text": "", "finish_reason": "stop"},
                                       {"id": "dev-1", "text": "#### 4", "error": "timeout"}])
        self.assertEqual(result["correct"], 0)
        self.assertEqual(result["failed_requests"], 3)
        self.assertEqual(result["incorrect"], 3)

    def test_truncation_requires_an_extractable_final_answer(self):
        records = items(3)
        result = score_items(records, [
            {"id": "dev-0", "text": "partial reasoning\n4", "finish_reason": "length"},
            {"id": "dev-1", "text": "work\n#### 4", "finish_reason": "length"},
            {"id": "dev-2", "text": r"\boxed{4}", "finish_reason": "length"},
        ])
        self.assertEqual(result["correct"], 2)
        self.assertEqual(result["truncated_answers"], 3)
        self.assertEqual(result["failed_requests"], 0)

    def test_dev_tolerance_is_fixed_to_original_reference(self):
        records = items(150)
        baseline = score_items(records, outputs(records))
        candidate = score_items(records, outputs(records, wrong=3))
        gate = evaluate_gate(candidate, baseline)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["minimum_correct"], 147)
        self.assertEqual(gate["paired_lost"], 3)
        self.assertEqual(gate["paired_gained"], 0)
        self.assertEqual(gate["wording"], TOLERANCE_WORDING)
        self.assertNotIn("no detected", gate["wording"])
        candidate = score_items(records, outputs(records, wrong=4))
        self.assertFalse(evaluate_gate(candidate, baseline)["passed"])

    def test_failed_eval_request_fails_candidate_even_inside_score_tolerance(self):
        records = items(150)
        baseline = score_items(records, outputs(records))
        answers = outputs(records)
        answers[0]["error"] = "timeout"
        candidate = score_items(records, answers)
        self.assertEqual(candidate["correct"], 149)
        self.assertFalse(evaluate_gate(candidate, baseline)["passed"])

    def test_final_gate_uses_300_and_paired_counts(self):
        records = items(300, "final")
        baseline = score_items(records, outputs(records))
        candidate = score_items(records, outputs(records, wrong=6))
        gate = evaluate_gate(candidate, baseline, split="final")
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["allowed_decrease"], 6)
        self.assertEqual(gate["difference_percentage_points"], -2)

    def test_small_fixture_scores_cannot_be_presented_as_real_gate(self):
        records = items(3)
        result = score_items(records, outputs(records))
        with self.assertRaises(ValueError):
            evaluate_gate(result, result)

    def test_gate_rejects_forged_aggregate_or_duplicate_pair_rows(self):
        records = items(150)
        baseline = score_items(records, outputs(records))
        candidate = score_items(records, outputs(records, wrong=4))
        candidate["correct"] = 150
        with self.assertRaises(ValueError):
            evaluate_gate(candidate, baseline)
        candidate = copy.deepcopy(baseline)
        candidate["results"][0] = copy.deepcopy(candidate["results"][1])
        with self.assertRaises(ValueError):
            evaluate_gate(candidate, baseline)

    def test_gate_rejects_changed_items_or_scorer_or_incomplete_pairs(self):
        records = items(150)
        baseline = score_items(records, outputs(records))
        for key, value in (("items_sha256", "different"), ("scorer_sha256", "different"),
                           ("results", []), ("item_ids", ["changed"])):
            candidate = copy.deepcopy(baseline)
            candidate[key] = value
            with self.assertRaises(ValueError):
                evaluate_gate(candidate, baseline)

    def test_manifests_require_exact_sizes_and_disjoint_ids_and_questions(self):
        dev, final = items(150), items(300, "final")
        manifest = validate_dataset_manifest(dev, final)
        self.assertEqual(manifest["dev_items"], 150)
        self.assertEqual(manifest["final_items"], 300)
        final[0]["id"] = dev[0]["id"]
        with self.assertRaises(ValueError):
            validate_dataset_manifest(dev, final)
        final[0]["id"] = "final-0"
        final[0]["prompt"] = dev[0]["prompt"]
        with self.assertRaises(ValueError):
            validate_dataset_manifest(dev, final)

    def test_unknown_duplicate_and_nonfinite_inputs_are_rejected(self):
        records = items(3)
        for answers in ([{"id": "unknown", "text": "4"}],
                        [{"id": "dev-0", "text": "4"}, {"id": "dev-0", "text": "4"}]):
            with self.assertRaises(ValueError):
                score_items(records, answers)
        for value in (float("nan"), float("inf"), True, None, ""):
            with self.assertRaises(ValueError):
                normalize_answer(value)


if __name__ == "__main__":
    unittest.main()
