"""Controller integration with synthetic fixtures only; no serving/provider calls."""

from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from servetune.artifacts import digest, file_hash, seal, write_json
from servetune.deadline import SessionDeadline, TimeBudgetExceeded
from servetune.ledger import Ledger
from servetune.quality import evaluate_gate, score_items
from servetune.study import PHASES, StudyController, initialize_study, run_study, verify_trial
from servetune.study_protocol import DEFAULT_STUDY


KNOBS = {"max_num_seqs": 256, "max_num_batched_tokens": 2048,
         "enable_chunked_prefill": True, "gpu_memory_utilization": .9}


class FakeClock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


class StudyControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "study"
        self.protocol = deepcopy(DEFAULT_STUDY)
        self.protocol["calibration"]["rates"] = [.1, .2]
        self.protocol["map"]["duration_s"] = 120
        self.protocol["tuning"]["max_trials"] = 2
        self.quiet = redirect_stdout(StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def initialize(self):
        return initialize_study(self.root, protocol=self.protocol, simulate=True)

    def test_full_pipeline_is_sealed_but_never_becomes_live_evidence(self):
        self.initialize()
        with patch("servetune.study_runner.ManagedEngine", side_effect=AssertionError("No GPU")), \
             patch("servetune.study_runner.PowerMeter", side_effect=AssertionError("No NVML")), \
             patch("servetune.study_planner.propose_spark", side_effect=AssertionError("No paid provider")):
            result = run_study(self.root)
        self.assertEqual(result["status"], "simulation_complete")
        self.assertEqual(result["completed_phases"], list(PHASES))
        self.assertFalse(result["floor"]["built"])
        self.assertIn("Synthetic", result["floor"]["reason"])
        self.assertTrue((self.root / "manifest.json").is_file())
        trials = [verify_trial(self.root / entry["path"]) for entry in result["trials"]]
        self.assertTrue(trials)
        self.assertTrue(all(row["mode"] == "synthetic_fixture" for row in trials))
        self.assertTrue(all(row["accepted_live_measurement"] is False for row in trials))
        frozen = json.loads((self.root / "frozen.json").read_text())
        seq_choices = set(self.protocol["map"]["max_num_seqs"]) | {frozen["engine_defaults"]["max_num_seqs"]}
        expected_map_runs = len(frozen["loads"]) * 2 * len(seq_choices) * 3
        self.assertEqual(len([entry for entry in result["trials"] if entry["phase"] == "map"]), expected_map_runs)
        self.assertEqual(len([entry for entry in result["trials"] if entry["phase"] == "ab"]), 10)
        declaration = json.loads((self.root / "tuning-declaration.json").read_text())
        self.assertEqual(set(result["arms"]), {"R", "S"})
        self.assertEqual(result["arms"]["R"]["budget_s"], result["arms"]["S"]["budget_s"])
        for arm in ("R", "S"):
            history = json.loads((self.root / f"arms/{arm}/history.json").read_text())
            self.assertEqual(history[0]["config"], declaration["baseline_config"])
            self.assertTrue(all(row["arm"] == arm for row in history))
        confirmation = json.loads((self.root / "confirmation.json").read_text())
        self.assertEqual(confirmation["status"], "complete")
        self.assertTrue(confirmation["single_use_final_set"])
        self.assertTrue(all(row["items"] == 300 for row in confirmation["quality_results"].values()))
        from servetune.study_report import verify_study
        self.assertEqual(verify_study(self.root)["headline_rows"], [])
        with self.assertRaises(ValueError):
            StudyController(self.root)

    def test_phase_resume_does_not_repeat_already_sealed_measurements(self):
        self.initialize()
        first = run_study(self.root, phase="calibration")
        self.assertEqual(first["completed_phases"], ["calibration"])
        original = {entry["id"]: (self.root / entry["path"] / "trial.json").read_bytes()
                    for entry in first["trials"]}
        controller = StudyController(self.root)
        resumed = controller.run("map")
        self.assertEqual(resumed["completed_phases"], ["calibration", "map"])
        for entry in resumed["trials"]:
            if entry["id"] in original:
                self.assertEqual((self.root / entry["path"] / "trial.json").read_bytes(), original[entry["id"]])
        ids = [entry["id"] for entry in resumed["trials"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_stale_controller_reloads_phase_checkpoint_under_the_lock(self):
        self.initialize()
        first, stale = StudyController(self.root), StudyController(self.root)
        first.run("calibration")
        resumed = stale.run("map")
        self.assertEqual(resumed["completed_phases"], ["calibration", "map"])

    def test_stale_controller_cannot_mutate_a_newly_sealed_study(self):
        self.initialize()
        first, stale = StudyController(self.root), StudyController(self.root)
        first.run()
        before = {path.relative_to(self.root).as_posix(): file_hash(path)
                  for path in self.root.rglob("*") if path.is_file()}
        with self.assertRaises(ValueError):
            stale.run()
        after = {path.relative_to(self.root).as_posix(): file_hash(path)
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_error_after_successful_seal_does_not_write_error_metadata_into_sealed_tree(self):
        self.initialize()
        def seal_then_raise(directory):
            seal(directory)
            raise OSError("Fixture failure after successful seal")
        with patch("servetune.study.seal", side_effect=seal_then_raise):
            with self.assertRaises(OSError):
                run_study(self.root)
        from servetune.study_report import verify_study
        self.assertTrue(verify_study(self.root)["root_manifest_verified"])
        state = json.loads((self.root / "state.json").read_text())
        self.assertEqual(state["status"], "simulation_complete")

    def test_frozen_declaration_and_trace_hashes_are_checked_before_new_measurements(self):
        for mode in ("declaration", "trace"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "study"
                initialize_study(root, protocol=self.protocol, simulate=True)
                run_study(root, phase="calibration")
                frozen_path = root / "frozen.json"
                frozen = json.loads(frozen_path.read_text())
                if mode == "declaration":
                    frozen["slo_s"] += 1
                    frozen_path.write_text(json.dumps(frozen))
                else:
                    trace_path = root / frozen["loads"][0]["trace"]
                    trace = json.loads(trace_path.read_text())
                    trace["requests"][0]["prompt"] = "Changed workload"
                    trace_path.write_text(json.dumps(trace))
                controller = StudyController(root)
                with patch.object(controller.runner, "measure", side_effect=AssertionError("No new measurement")):
                    with self.assertRaises(ValueError):
                        controller.run("map")

    def test_orphan_frozen_write_is_recovered_from_same_sealed_calibration(self):
        self.initialize()
        run_study(self.root, phase="calibration")
        original_frozen = (self.root / "frozen.json").read_bytes()
        state_path = self.root / "state.json"
        state = json.loads(state_path.read_text())
        state["completed_phases"] = []
        state["frozen_sha256"] = None
        state.pop("frozen", None)
        state_path.write_text(json.dumps(state))
        controller = StudyController(self.root)
        with patch.object(controller.runner, "measure", side_effect=AssertionError("No calibration rerun")):
            result = controller.run("calibration")
        self.assertEqual(result["completed_phases"], ["calibration"])
        self.assertEqual((self.root / "frozen.json").read_bytes(), original_frozen)
        self.assertIsNotNone(controller.state["frozen_sha256"])

    def test_sealed_trial_missing_from_mutable_index_is_recovered_without_execution(self):
        self.initialize()
        controller = StudyController(self.root)
        trace = controller._trace("resume-check", .1)
        engine = controller._engine(defaults=True)
        first = controller._trial("recover-me", engine, "bf16", trace, phase="map")
        controller.state["trials"] = []  # Simulate a crash before mutable-index persistence.
        controller._save()
        resumed = StudyController(self.root)
        with patch.object(resumed.runner, "measure", side_effect=AssertionError("No repeat allowed")):
            recovered = resumed._trial("recover-me", engine, "bf16", trace, phase="map")
        self.assertEqual(recovered, first)
        self.assertEqual([entry["id"] for entry in resumed.state["trials"]], ["recover-me"])
        with patch.object(resumed.runner, "measure", side_effect=AssertionError("No repeat allowed")):
            resumed._trial("recover-me", engine, "bf16", trace, phase="map")
        self.assertEqual(len(resumed.state["trials"]), 1)

    def test_tampered_trial_or_changed_protocol_fails_before_new_execution(self):
        self.initialize()
        controller = StudyController(self.root)
        trace = controller._trace("integrity-check", .1)
        engine = controller._engine(defaults=True)
        controller._trial("original", engine, "bf16", trace, phase="map")
        (self.root / "trials/original/trial.json").write_text("{}")
        with patch.object(controller.runner, "measure", side_effect=AssertionError("No new measurement")):
            with self.assertRaises(ValueError):
                controller._trial("original", engine, "bf16", trace, phase="map")
        protocol = json.loads((self.root / "protocol.json").read_text())
        protocol["tuning"]["seed"] += 1
        (self.root / "protocol.json").write_text(json.dumps(protocol))
        with self.assertRaises(ValueError):
            StudyController(self.root)

    def test_sealed_dev_trial_recovers_lost_index_and_quality_cache_without_scoring(self):
        self.initialize()
        controller = StudyController(self.root)
        trace = controller._trace("cache-recovery", .1)
        engine = controller._engine(KNOBS)
        original = controller._trial("orphan-dev", engine, "bf16", trace, phase="map", quality_split="dev")
        controller.state["trials"] = []
        controller.state["quality_cache"] = {}
        controller._save()
        resumed = StudyController(self.root)
        with patch.object(resumed.runner, "measure", side_effect=AssertionError("No quality rerun")):
            resumed._restore_quality_cache()
        cached = resumed._quality_cached(engine, "bf16")
        self.assertEqual(cached["score"], original["quality"])
        self.assertTrue(cached["gate"]["passed"])
        self.assertEqual(resumed.state["trials"][0]["quality_summary"]["items"], 150)

    def test_fixed_trial_id_cannot_gain_an_evaluation_split_on_resume(self):
        self.initialize()
        controller = StudyController(self.root)
        trace = controller._trace("fixed-identity", .1)
        engine = controller._engine(defaults=True)
        controller._trial("no-quality", engine, "bf16", trace, phase="map")
        with patch.object(controller.runner, "measure", side_effect=AssertionError("No hidden scoring")):
            with self.assertRaises(ValueError):
                controller._trial("no-quality", engine, "bf16", trace, phase="map", quality_split="dev")

    def test_known_failed_quality_gate_is_carried_to_later_same_config_repeats(self):
        self.initialize()
        controller = StudyController(self.root)
        trace = controller._trace("failed-quality", .1)
        engine = controller._engine(KNOBS)
        outputs = [{"id": row["id"], "text": "#### wrong" if index < 4 else f"#### {row['answer']}",
                    "finish_reason": "stop"} for index, row in enumerate(controller.runner.dev)]
        score = score_items(controller.runner.dev, outputs)
        gate = evaluate_gate(score, controller.runner.baseline_score, "dev")
        self.assertFalse(gate["passed"])
        controller.state["quality_cache"][digest({"engine": engine, "dtype": "bf16", "split": "dev"})] = {
            "trial": "earlier-quality-attempt", "score": score, "gate": gate}
        trials = [controller._trial(f"later-{index}", engine, "bf16", trace, phase="map") for index in range(3)]
        for entry in controller.state["trials"]:
            self.assertFalse(entry["quality_gate"]["passed"])
            self.assertEqual(entry["quality_summary"]["correct"], 146)
        self.assertEqual(controller._summary(trials, 3)["status"], "fail")

    def test_final_set_is_claimed_once_even_if_its_first_attempt_is_interrupted(self):
        self.initialize()
        controller = StudyController(self.root)
        trace = controller._trace("final-check", .1)
        engine = controller._engine(defaults=True)
        with patch.object(controller.runner, "measure", side_effect=TimeBudgetExceeded("Fixture cutoff")) as call:
            with self.assertRaises(TimeBudgetExceeded):
                controller._trial("final-interrupted", engine, "bf16", trace,
                                  phase="confirmation", quality_split="final")
        self.assertEqual(call.call_count, 1)
        resumed = StudyController(self.root)
        with patch.object(resumed.runner, "measure", side_effect=AssertionError("Final set reuse")) as repeat:
            with self.assertRaises(ValueError):
                resumed._trial("final-another-name", engine, "bf16", trace,
                               phase="confirmation", quality_split="final")
        repeat.assert_not_called()

    def test_completed_final_trial_can_be_replayed_but_not_rescored_under_new_name(self):
        self.initialize()
        controller = StudyController(self.root)
        trace = controller._trace("final-once", .1)
        engine = controller._engine(defaults=True)
        original = controller._trial("final-complete", engine, "bf16", trace,
                                     phase="confirmation", quality_split="final")
        with patch.object(controller.runner, "measure", side_effect=AssertionError("Final rerun")) as repeat:
            reused = controller._trial("final-complete", engine, "bf16", trace,
                                       phase="confirmation", quality_split="final")
            self.assertEqual(reused, original)
            with self.assertRaises(ValueError):
                controller._trial("final-renamed", engine, "bf16", trace,
                                   phase="confirmation", quality_split="final")
        repeat.assert_not_called()

    def prepare_search(self, *, clock, planner, trial_seconds=1000, arm_budget=7000, max_trials=2,
                       trial_estimate_s=1):
        self.protocol["tuning"].update(arm_budget_s=arm_budget, max_trials=max_trials, trial_estimate_s=trial_estimate_s)
        self.initialize()
        ledger_path = self.root / "fixture-ledger.json"
        Ledger(ledger_path).initialize()
        controller = StudyController(self.root, ledger_path=ledger_path, planner=planner)
        trace = controller._trace("search-load", .1)
        controller.state["frozen"] = {
            "loads": [{"label": "load-1", "trace": "traces/search-load.json",
                       "trace_sha256": digest(trace), "arrival_rate": .1}],
            "tuning_load": "load-1", "engine_defaults": KNOBS, "slo_s": 15,
            "preflight_observed_cv": .005,
        }
        write_json(self.root / "ab.json", {"fp8_quality_passed": False})
        # Exercise the paid-planner branch with an injected local function. All
        # measurements below remain explicit fixtures; no real provider/GPU runs.
        controller.simulate = False
        controller.final_reserve_s = 1
        calls = []
        def trial(name, engine, dtype, frozen_trace, **kwargs):
            clock.advance(trial_seconds)
            calls.append({"name": name, "arm": kwargs.get("arm"), "config": deepcopy(engine),
                          "quality_split": kwargs.get("quality_split")})
            measured = {"status": "pass", "all_requests_completed": True,
                        "joules_per_output_token": 100, "joules_per_completed_request": 100,
                        "generated_tokens": 100, "completed_requests": 10, "joules": 1000,
                        "p95_latency_s": 1, "duration_s": 120, "output_tokens_per_second": 1,
                        "trace_sha256": digest(frozen_trace)}
            return {"status": "pass", "mode": "synthetic_fixture", "measurement": measured,
                    "quality_gate": {"passed": True}, "allocated_seconds": trial_seconds}
        controller._trial = trial
        return controller, calls

    def test_search_allocated_clocks_are_isolated_and_planner_gets_only_own_history(self):
        clock, contexts = FakeClock(), []
        def planner(current, history, space, baseline, ledger_path, out_dir, **kwargs):
            contexts.append({"current": deepcopy(current), "history": deepcopy(history), "baseline": deepcopy(baseline)})
            clock.advance(800)
            value = next(value for value in space["max_num_seqs"] if value != current["max_num_seqs"])
            proposal = {"hypothesis": "Fixture hypothesis", "expected_effect": "Unmeasured",
                        "diff": {"max_num_seqs": value}}
            return {"status": "pass", "proposal": proposal}
        with patch("servetune.study.time.monotonic", clock):
            controller, calls = self.prepare_search(clock=clock, planner=planner)
            controller.search()
        self.assertEqual(controller.state["arms"]["R"]["trials"], 2,
                         "S's longer trial must not inflate R's future admission estimate")
        self.assertEqual(controller.state["arms"]["S"]["trials"], 1)
        self.assertEqual(controller.state["arms"]["R"]["elapsed_s"], 6000)
        self.assertEqual(controller.state["arms"]["S"]["elapsed_s"], 3800)
        self.assertEqual(controller.state["arms"]["S"]["planner_wait_s"], 800)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["history"], [])
        self.assertEqual(contexts[0]["baseline"]["config"], KNOBS)
        self.assertIn("summary", contexts[0]["baseline"])
        self.assertEqual(contexts[0]["baseline"]["slo_s"], 15)
        self.assertEqual(contexts[0]["baseline"]["reference_items"], 150)

    def test_failed_planner_wait_is_charged_and_reported_without_trial_execution(self):
        clock = FakeClock()
        def planner(*args, **kwargs):
            clock.advance(800)
            return {"status": "fail", "planner_wait_seconds": 800, "paid_calls": 1}
        with patch("servetune.study.time.monotonic", clock):
            controller, calls = self.prepare_search(clock=clock, planner=planner, max_trials=1)
            controller.search()
        self.assertEqual(controller.state["arms"]["S"]["elapsed_s"], 800)
        self.assertEqual(controller.state["arms"]["S"]["planner_wait_s"], 800)
        self.assertFalse(any(row["arm"] == "S" for row in calls))
        history = json.loads((self.root / "arms/S/history.json").read_text())
        self.assertFalse(history[0]["decision"]["accepted"])
        self.assertEqual(history[0]["allocated_seconds"], 800)

    def test_tuning_declaration_is_recovered_without_rewriting_after_pre_arm_crash(self):
        clock = FakeClock()
        def planner(current, history, space, baseline, ledger_path, out_dir, **kwargs):
            value = next(value for value in space["max_num_seqs"] if value != current["max_num_seqs"])
            return {"status": "pass", "proposal": {"hypothesis": "Fixture", "expected_effect": "Unmeasured",
                                                     "diff": {"max_num_seqs": value}}}
        with patch("servetune.study.time.monotonic", clock):
            controller, calls = self.prepare_search(clock=clock, planner=planner, trial_seconds=1)
            frozen = deepcopy(controller.state["frozen"])
            with patch.object(controller, "_save", side_effect=OSError("Crash after declaration")):
                with self.assertRaises(OSError):
                    controller.search()
            declaration = (self.root / "tuning-declaration.json").read_bytes()
            resumed = StudyController(self.root, ledger_path=controller.ledger_path, planner=planner)
            resumed.simulate = False
            resumed.final_reserve_s = 1
            resumed.state["frozen"] = frozen
            resumed._trial = controller._trial
            resumed.search()
        self.assertEqual((self.root / "tuning-declaration.json").read_bytes(), declaration)
        self.assertEqual(resumed.state["arms"]["R"]["trials"], 2)
        self.assertEqual(resumed.state["arms"]["S"]["trials"], 2)

    def test_global_time_admission_stops_both_arms_before_an_unbalanced_last_pair(self):
        clock = FakeClock()
        with patch("servetune.study.time.monotonic", clock):
            controller, calls = self.prepare_search(clock=clock, planner=Mock(side_effect=AssertionError("No paid proposal")),
                                                    trial_estimate_s=4200)
            original_save = controller._save
            narrowed = False
            def save_then_narrow_session():
                nonlocal narrowed
                original_save()
                if controller.state["arms"] and not narrowed:
                    # Both nominal arm budgets were already declared equally.
                    # Remaining global time can fit one estimate, but not both.
                    narrowed = True
                    controller.deadline = SessionDeadline(6530, clock=clock)
            with patch.object(controller, "_save", side_effect=save_then_narrow_session):
                controller.search()
        self.assertEqual(controller.state["arms"]["R"]["trials"], 0)
        self.assertEqual(controller.state["arms"]["S"]["trials"], 0)
        self.assertFalse(any(row["arm"] for row in calls))
        for arm in ("R", "S"):
            self.assertIn("balanced arm pair", controller.state["arms"][arm]["stop_reason"])


if __name__ == "__main__":
    unittest.main()
