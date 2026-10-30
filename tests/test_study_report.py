"""Offline report evidence boundaries; no GPU, provider or rental calls."""

import csv
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from servetune.artifacts import digest, seal, write_json
from servetune.quality import score_items
from servetune.study_report import StudyVerificationError, generate_report, verify_study


class StudyReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "study"
        self.root.mkdir()
        self.protocol = {"schema_version": 1, "tuning": {"slo_s": 3}}
        write_json(self.root / "protocol.json", self.protocol)
        self.index = []

    def trial(self, name, *, phase="map", mode="live", status="pass", dtype="bf16",
              config_label=None, arm=None, score=None, decision=None, hypothesis=None):
        directory = self.root / "trials" / name
        directory.mkdir(parents=True)
        config = {"max_num_seqs": 64}
        trace = {"requests": [{"id": "one", "arrival_s": 0, "prompt": "Example fixture"}]}
        measured = {"status": "pass", "joules": 100., "generated_tokens": 100,
                    "completed_requests": 1, "scheduled_requests": 1, "all_requests_completed": True,
                    "joules_per_output_token": 1., "joules_per_completed_request": 100.,
                    "p95_latency_s": .5, "p95_ttft_s": .1, "output_tokens_per_second": 10.,
                    "trace_sha256": digest(trace), "energy": {"samples": [
                        {"monotonic_s": 10, "power_w": 100}, {"monotonic_s": 11, "power_w": 120}]}}
        trial = {"schema_version": 1, "mode": mode, "status": status, "config": config,
                 "config_sha256": digest(config), "trace_sha256": digest(trace), "dtype": dtype,
                 "hardware": {"gpu": {"uuid": "GPU-local-test-fixture"}}, "measurement": measured,
                 "quality": score, "quality_gate": None, "allocated_seconds": 12.5}
        write_json(directory / "trial.json", trial)
        write_json(directory / "trace.json", trace)
        seal(directory)
        index = {"id": name, "path": f"trials/{name}", "phase": phase, "arm": arm,
                 "load_label": "load-1", "config_label": config_label or name}
        if decision is not None:
            index["decision"] = decision
        if hypothesis is not None:
            index["hypothesis"] = hypothesis
        self.index.append(index)
        return directory

    def finish(self, *, sealed=True, floor=False, mode="live", confirmation=None):
        write_json(self.root / "study.json", {"mode": mode, "status": "complete" if sealed else "partial",
                   "protocol_sha256": digest(self.protocol), "trials": self.index,
                   "floor": {"built": floor, "reason": "Fixture controller attestation"}})
        if confirmation is not None:
            write_json(self.root / "confirmation.json", confirmation)
        if sealed:
            seal(self.root)

    def final_score(self, correct):
        items = [{"id": f"final-{i}", "answer": "42"} for i in range(300)]
        outputs = [{"id": row["id"], "text": "#### 42" if i < correct else "#### 0",
                    "finish_reason": "stop"} for i, row in enumerate(items)]
        return score_items(items, outputs)

    def test_tuning_measurements_never_enter_confirmation_csv(self):
        self.trial("tuning", phase="search", arm="R")
        self.trial("confirmation", phase="confirmation", config_label="bf16-default", score=self.final_score(300))
        self.finish()
        paths = generate_report(self.root)
        raw = list(csv.DictReader(io.StringIO(Path(paths["trials_csv"]).read_text())))
        headline = list(csv.DictReader(io.StringIO(Path(paths["headline_csv"]).read_text())))
        self.assertEqual({row["id"] for row in raw}, {"tuning", "confirmation"})
        self.assertEqual([row["id"] for row in headline], ["confirmation"])
        self.assertTrue(verify_study(self.root)["root_manifest_verified"])

    def test_unsealed_checkpoint_never_publishes_headline_or_floor(self):
        self.trial("confirmation", phase="confirmation")
        self.finish(sealed=False, floor=True)
        verified = verify_study(self.root)
        self.assertFalse(verified["root_manifest_verified"])
        self.assertEqual(verified["headline_rows"], [])
        self.assertFalse(verified["floor"]["established"])
        paths = generate_report(self.root)
        self.assertEqual(list(csv.DictReader(io.StringIO(Path(paths["headline_csv"]).read_text()))), [])
        self.assertIn("No headline result is available", Path(paths["results"]).read_text())

    def test_synthetic_fixture_cannot_support_headline_floor_or_final_quality(self):
        self.trial("fake-map", mode="synthetic_fixture")
        self.trial("fake-confirmation", phase="confirmation", mode="synthetic_fixture", score=self.final_score(300))
        self.finish(floor=True, mode="synthetic_fixture", confirmation={
            "baseline_label": "bf16-default", "quality_results": {"bf16-default": self.final_score(300)}})
        verified = verify_study(self.root)
        self.assertEqual(verified["headline_rows"], [])
        self.assertFalse(verified["floor"]["established"])
        self.assertEqual(verified["final_paired_quality"], [])
        self.assertTrue(all(not row["live_observation"] for row in verified["rows"]))

    def test_failed_confirmation_is_retained_with_status(self):
        self.trial("failed-confirmation", phase="confirmation", status="fail", config_label="fp8-default")
        self.finish()
        paths = generate_report(self.root)
        rows = list(csv.DictReader(io.StringIO(Path(paths["headline_csv"]).read_text())))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "fail")
        self.assertEqual(rows[0]["eligible"], "False")

    def test_final_quality_pairs_use_identical_300_item_records(self):
        self.trial("baseline", phase="confirmation", config_label="bf16-default", score=self.final_score(300))
        self.trial("fp8", phase="confirmation", config_label="fp8-default", dtype="fp8", score=self.final_score(294))
        self.finish()
        verified = verify_study(self.root)
        fp8 = next(row for row in verified["final_paired_quality"] if row["config_label"] == "fp8-default")
        self.assertEqual(fp8["paired_lost"], 6)
        self.assertEqual(fp8["paired_gained"], 0)
        self.assertTrue(fp8["passed"])
        self.assertEqual(fp8["difference_percentage_points"], -2)

    def test_bad_final_quality_stays_visible_but_is_ineligible(self):
        self.trial("baseline", phase="confirmation", config_label="bf16-default", score=self.final_score(300))
        self.trial("fp8", phase="confirmation", config_label="fp8-default", dtype="fp8", score=self.final_score(290))
        self.finish()
        verified = verify_study(self.root)
        row = next(row for row in verified["headline_rows"] if row["config_label"] == "fp8-default")
        self.assertFalse(row["final_quality_passed"])
        self.assertFalse(row["eligible"])
        self.assertEqual(len(verified["headline_rows"]), 2)

    def test_tampered_trial_file_and_mutable_final_index_are_rejected(self):
        directory = self.trial("map")
        self.finish()
        (directory / "trial.json").write_text("{}")
        with self.assertRaises(StudyVerificationError):
            verify_study(self.root)

    def test_modified_final_index_cannot_relabel_search_as_confirmation(self):
        self.trial("tuning", phase="search")
        self.finish()
        path = self.root / "study.json"
        data = json.loads(path.read_text())
        data["trials"][0]["phase"] = "confirmation"
        path.write_text(json.dumps(data))
        with self.assertRaises(StudyVerificationError):
            verify_study(self.root)

    def test_path_traversal_and_symlinks_are_rejected(self):
        self.index.append({"id": "escape", "path": "../outside", "phase": "confirmation"})
        self.finish(sealed=False)
        with self.assertRaises(StudyVerificationError):
            verify_study(self.root)
        outside = Path(self.temporary.name) / "secret"
        outside.write_text("not evidence")
        (self.root / "linked").symlink_to(outside)
        with self.assertRaises(StudyVerificationError):
            verify_study(self.root)

    def test_partial_unsealed_trial_is_listed_without_fabricated_metrics(self):
        self.index.append({"id": "pending", "path": "trials/pending", "phase": "search", "arm": "S"})
        self.finish(sealed=False)
        verified = verify_study(self.root)
        self.assertEqual(verified["rows"][0]["status"], "unsealed")
        self.assertIsNone(verified["rows"][0]["joules"])
        self.assertFalse(verified["rows"][0]["verified"])

    def test_histories_preserve_schema_rejections_and_accepted_trial_hypotheses(self):
        self.trial("search-S-000-00", phase="search", arm="S", config_label="search-S-000")
        write_json(self.root / "arms/S/history.json", [
            {"trial": 0, "proposal": {"hypothesis": "A bounded hypothesis"}, "decision": {
                "accepted": True, "reasons": [], "length_drift": {"flagged": True, "eligible": True}},
             "planner_wait_seconds": .3, "allocated_seconds": 100},
            {"trial": 1, "decision": {"accepted": False, "reasons": ["Schema rejected"]},
             "allocated_seconds": 2}])
        self.finish()
        verified = verify_study(self.root)
        self.assertEqual(len(verified["timeline"]), 2)
        self.assertEqual(verified["rows"][0]["hypothesis"], "A bounded hypothesis")
        self.assertTrue(verified["rows"][0]["accepted"])
        self.assertTrue(verified["rows"][0]["length_drift_flagged"])
        self.assertTrue(verified["rows"][0]["eligible"])
        paths = generate_report(self.root)
        decisions = list(csv.DictReader(io.StringIO(Path(paths["decisions_csv"]).read_text())))
        self.assertEqual(decisions[1]["decision_reason"], "Schema rejected")

    def test_html_is_offline_and_untrusted_hypotheses_cannot_close_script(self):
        attack = '</script><img src=x onerror="alert(1)">'
        self.trial("trial", phase="search", hypothesis=attack)
        self.finish()
        paths = generate_report(self.root)
        document = Path(paths["dashboard"]).read_text()
        self.assertNotIn(attack, document)
        self.assertIn("\\u003c/script\\u003e", document)
        self.assertNotIn("fetch(", document)
        self.assertNotIn("XMLHttpRequest", document)
        self.assertIn("textContent", document)
        self.assertIn("No recorded observations", document)

    def test_csv_text_cannot_become_a_spreadsheet_formula(self):
        self.trial("trial", hypothesis="=HYPERLINK(\"example\")")
        self.finish()
        paths = generate_report(self.root)
        rows = list(csv.DictReader(io.StringIO(Path(paths["trials_csv"]).read_text())))
        self.assertTrue(rows[0]["hypothesis"].startswith("'="))

    def test_svg_exports_are_standalone_valid_xml_and_report_does_not_modify_study(self):
        self.trial("map")
        self.finish(floor=True)
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        paths = generate_report(self.root)
        for path in Path(paths["svg_dir"]).glob("*.svg"):
            self.assertEqual(ET.parse(path).getroot().tag, "{http://www.w3.org/2000/svg}svg")
        self.assertEqual(before, {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        with self.assertRaises(StudyVerificationError):
            generate_report(self.root, self.root / "reports")


if __name__ == "__main__":
    unittest.main()
