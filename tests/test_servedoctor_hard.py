import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from servedoctor import catalog
from servedoctor.cli import main as cli_main
from servedoctor.fakeserve import FakeServer
from servedoctor.hard import BENIGN_KNOBS, INTERACTING_KNOBS, generate_hard
from servedoctor.live import _execute
from servedoctor.loadgen import Gateway
from servedoctor.record import JOB_MODULES, ContentionJob, record_study, scenario_jobs
from servedoctor.scenarios import build_prompt_pools
from servedoctor.scoring import score_one
from servedoctor.validity import check_incident

ROOT = Path(__file__).resolve().parents[1]
HARD = json.loads((ROOT / "configs" / "servedoctor-hard.json").read_text())
QUESTIONS = [f"Question {i}: a shop sells {i} pens and {i + 2} pencils. How many items?" for i in range(400)]


def hard_study(**changes):
    study = copy.deepcopy(HARD)
    study["capacity_rps"] = 8
    study.update(changes)
    return study


class GenerationTests(unittest.TestCase):
    def test_deterministic_and_shaped_as_declared(self):
        first, keys = generate_hard(hard_study())
        second, _ = generate_hard(hard_study())
        self.assertEqual(first, second)
        self.assertEqual(len(keys), 16)
        self.assertEqual(first[-1]["id"], "reference")
        self.assertEqual(sum(len(k["root_causes"]) == 2 for k in keys), 4)
        self.assertEqual(sum(k["root_causes"] == ["healthy"] for k in keys), 3)
        self.assertTrue(all(k["split"] == "hard" for k in keys))

    def test_no_label_leaks_into_what_agents_see(self):
        scenarios, keys = generate_hard(hard_study())
        for scenario in scenarios:
            visible = json.dumps(scenario["events"])
            for cause in catalog.INCIDENT_CAUSES:
                self.assertNotIn(cause, visible)
            modules = [job["module"] for job in scenario["jobs"]]
            self.assertEqual(len(modules), len(set(modules)))
            self.assertTrue(set(modules) <= set(JOB_MODULES))
        # Names are shared between culprits and decoys across incidents.
        roles = {}
        for scenario in scenarios:
            for job in scenario["jobs"]:
                roles.setdefault(job["module"], set()).add(job["role"])
        self.assertTrue(any(len(r) == 2 for r in roles.values()))

    def test_every_deploy_changes_engine_knobs_and_benign_ones_are_safe(self):
        scenarios, keys = generate_hard(hard_study())
        by_id = {k["id"]: k for k in keys}
        with_engine_noise = 0
        for scenario in scenarios[:-1]:
            deploy = next(e for e in scenario["events"] if e["kind"] == "deploy")
            answer = by_id[scenario["id"]]
            benign = answer["red_herrings"]["benign_knobs"]
            with_engine_noise += bool(benign)
            for knob in benign:
                self.assertEqual(scenario["engine"][knob], BENIGN_KNOBS[knob])
                self.assertIn(knob, deploy["config_diff"])
                for cause in answer["root_causes"]:
                    self.assertNotIn(knob, INTERACTING_KNOBS.get(cause, set()))
        self.assertGreaterEqual(with_engine_noise, 13)

    def test_onsets_and_jobs_follow_causes(self):
        scenarios, keys = generate_hard(hard_study())
        for scenario, answer in zip(scenarios, keys):
            causes = answer["root_causes"]
            jobs = scenario_jobs(scenario)
            self.assertEqual(sum(j["role"] == "contention" for j in jobs), "gpu_contention" in causes)
            self.assertEqual(any(j["role"] == "decoy" for j in jobs), answer["red_herrings"]["decoy"])
            if causes == ["healthy"]:
                self.assertIsNone(answer["onset_s"])
            elif "traffic_surge" in causes or "long_prompt_flood" in causes or "gpu_contention" in causes:
                self.assertEqual(answer["onset_s"], 120)
            else:
                self.assertEqual(answer["onset_s"], 0)

    def test_invalid_specs_are_rejected(self):
        bad = hard_study()
        bad["hard_incidents"] = [{"name": "mixed", "causes": ["traffic_surge", "batch_limit_too_low"],
                                  "surge_multiplier": 1.2, "engine": {"max_num_seqs": 8}}]
        with self.assertRaises(ValueError):
            generate_hard(bad)
        bad["hard_incidents"] = [{"name": "kv", "causes": ["kv_cache_starvation"],
                                  "engine": {"gpu_memory_utilization": 0.6},
                                  "benign_knobs_forced": ["max_num_seqs"]}]
        with self.assertRaises(ValueError):
            generate_hard(bad)


class CompoundJudgingTests(unittest.TestCase):
    config = {"max_num_seqs": 16, "max_model_len": 1280, "gpu_memory_utilization": 0.86}

    def act(self, raw):
        return catalog.validate_action(raw, current_config=self.config)

    def test_both_fixed_one_fixed_and_harm(self):
        causes = ["batch_limit_too_low", "context_limit_too_small"]
        seqs = self.act({"type": "set_engine_config", "knob": "max_num_seqs", "value": 64})
        length = self.act({"type": "set_engine_config", "knob": "max_model_len", "value": 4096})
        both = catalog.judge_compound(causes, [seqs, length], current_config=self.config)
        self.assertTrue(both["fixes_all"])
        self.assertFalse(both["harmful"])
        one = catalog.judge_compound(causes, [seqs], current_config=self.config)
        self.assertTrue(one["fixes"])
        self.assertFalse(one["fixes_all"])
        shed = self.act({"type": "gateway_rate_limit", "max_rps": 2})
        self.assertTrue(catalog.judge_compound(causes, [length, shed], current_config=self.config)["harmful"])

    def test_stopping_a_decoy_is_harmful_even_with_a_real_fix(self):
        causes = ["traffic_surge", "gpu_contention"]
        limit = self.act({"type": "gateway_rate_limit", "max_rps": 8})
        decoy = self.act({"type": "stop_gpu_process", "pid": 777})
        culprit = self.act({"type": "stop_gpu_process", "pid": 555})
        good = catalog.judge_compound(causes, [limit, culprit], current_config=self.config, contention_pids=[555])
        self.assertTrue(good["fixes_all"])
        self.assertFalse(good["harmful"])
        bad = catalog.judge_compound(causes, [limit, decoy], current_config=self.config, contention_pids=[555])
        self.assertTrue(bad["harmful"])
        self.assertFalse(bad["fixes_all"])


class CompoundScoringTests(unittest.TestCase):
    def result(self, root_cause, actions, t=150):
        return {"arm": "spark", "engine_config": {"max_num_seqs": 64}, "checkpoints": 5, "trail": [],
                "final": {"root_cause": root_cause, "actions": actions, "t": t}}

    def test_either_cause_is_a_correct_diagnosis(self):
        answer = {"id": "hard-01", "split": "hard", "root_cause": "traffic_surge",
                  "root_causes": ["traffic_surge", "gpu_contention"], "severity_index": 0, "onset_s": 120,
                  "variant": "surge-plus-contention"}
        runtime = {"contention_pids": [555], "decoy_pids": [777]}
        row = score_one(self.result("gpu_contention", [{"type": "stop_gpu_process", "pid": 555}]), answer, runtime)
        self.assertTrue(row["diagnosis_correct"])
        self.assertTrue(row["fix_proposed"])
        self.assertFalse(row["complete_fix"])
        self.assertEqual(row["truth"], "traffic_surge+gpu_contention")
        full = score_one(self.result("traffic_surge", [{"type": "gateway_rate_limit", "max_rps": 8.0},
                                                       {"type": "stop_gpu_process", "pid": 555}]), answer, runtime)
        self.assertTrue(full["complete_fix"])
        decoy = score_one(self.result("gpu_contention", [{"type": "stop_gpu_process", "pid": 777}]), answer, runtime)
        self.assertTrue(decoy["stopped_decoy"])
        self.assertTrue(decoy["harmful"])
        self.assertFalse(decoy["fix_proposed"])

    def test_early_flag_is_a_false_alarm(self):
        answer = {"id": "hard-02", "split": "hard", "root_cause": "traffic_surge", "root_causes": ["traffic_surge"],
                  "severity_index": 0, "onset_s": 120}
        row = score_one(self.result("traffic_surge", [{"type": "gateway_rate_limit", "max_rps": 8.0}], t=60),
                        answer, {})
        self.assertTrue(row["false_alarm"])
        self.assertFalse(row["detected"])
        self.assertTrue(row["harmful"])


class JobTests(unittest.TestCase):
    def test_command_uses_whitelisted_module_and_period(self):
        job = ContentionJob()
        with patch("servedoctor.record.subprocess.Popen") as popen:
            popen.return_value.pid = 4321
            job.start(30, 0.02, 1024, module="servedoctor.jobs.thumbnail_index", period=1.0)
        command = popen.call_args[0][0]
        self.assertEqual(command[1:3], ["-m", "servedoctor.jobs.thumbnail_index"])
        self.assertEqual(command[-2:], ["--period", "1.0"])
        with self.assertRaises(ValueError):
            job.start(30, 0.5, 1024, module="os")

    def test_v0_command_is_unchanged(self):
        job = ContentionJob()
        with patch("servedoctor.record.subprocess.Popen") as popen:
            popen.return_value.pid = 4321
            job.start(30, 0.4, 8192)
        command = popen.call_args[0][0]
        self.assertEqual(command[1:], ["-m", "servedoctor.jobs.embedding_batch", "--seconds", "30",
                                       "--duty", "0.4", "--size", "8192"])

    def test_wrapper_modules_import(self):
        import importlib
        for module in JOB_MODULES:
            self.assertTrue(callable(importlib.import_module(module).main))


class FakeJob:
    started = []

    def __init__(self):
        self.pid = None
        self.stopped = False

    def start(self, seconds, duty, size, module="servedoctor.jobs.embedding_batch", period=None):
        self.pid = 9000 + len(FakeJob.started)
        FakeJob.started.append({"pid": self.pid, "module": module, "duty": duty, "period": period})
        return self.pid

    def owns(self, pid):
        return pid == self.pid

    def stop(self):
        self.stopped = True


class RecordAndExecuteTests(unittest.TestCase):
    def test_recording_writes_contention_and_decoy_pids(self):
        FakeJob.started = []
        study = hard_study()
        study["timing"] = {"pre_onset_s": 1, "fault_s": 2, "checkpoint_s": 1, "settle_s": 1}
        study["prompt_tokens"] = {"medium": [300, 400], "long": [600, 800]}
        scenarios, keys = generate_hard(study)
        target = next(k for k in keys if k["variant"] == "long-prompt-plus-contention")
        scenario = next(s for s in scenarios if s["id"] == target["id"])
        for job in scenario["jobs"]:
            job["onset_s"] = min(job["onset_s"], 0.5)
        pools = build_prompt_pools(QUESTIONS, study["prompt_tokens"], 2, per_class=6)
        with tempfile.TemporaryDirectory() as tmp:
            serving = {"model_id": "fake/fake", "model_revision": "0" * 40, "port": 8000}
            record_study([scenario], serving=serving, pools=pools, out_dir=tmp,
                         engine_factory=lambda config, path, dtype: FakeServer(config, path, dtype),
                         log=lambda *_: None, drain_timeout_s=10, job_factory=FakeJob)
            runtime = json.loads((Path(tmp) / "answers" / "runtime" / f"{target['id']}.json").read_text())
            self.assertEqual(len(runtime["contention_pids"]), 1)
            self.assertEqual(len(runtime["decoy_pids"]), 1)
            self.assertNotEqual(runtime["contention_pids"], runtime["decoy_pids"])
            modules = {row["module"] for row in FakeJob.started}
            self.assertEqual(modules, {job["module"] for job in scenario["jobs"]})

    def test_live_executor_stops_only_the_owning_job(self):
        first, second = FakeJob(), FakeJob()
        first.pid, second.pid = 11, 22
        action = {"type": "stop_gpu_process", "pid": 22}
        record = _execute(action, slot=type("Slot", (), {"knobs": {}})(), gateway=Gateway(),
                          jobs=[first, second], log=lambda *_: None)
        self.assertEqual(record["status"], "executed")
        self.assertTrue(second.stopped)
        self.assertFalse(first.stopped)
        refused = _execute({"type": "stop_gpu_process", "pid": 33}, type("Slot", (), {"knobs": {}})(),
                           Gateway(), [first], lambda *_: None)
        self.assertTrue(refused["status"].startswith("refused"))


class ValidityTests(unittest.TestCase):
    def write(self, root, requests, status="completed"):
        root.mkdir(parents=True)
        (root / "recording.json").write_text(json.dumps({"status": status, "duration_s": 120}))
        (root / "slo.json").write_text(json.dumps({"p95_latency_s": 10, "max_error_rate": 0.01}))
        (root / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in requests))

    def requests(self, slow_after=None):
        rows = []
        for i in range(240):
            t = i * 0.5
            latency = 30.0 if slow_after is not None and t >= slow_after else 4.0
            rows.append({"t_sched": t, "status": "ok", "latency_s": latency})
        return rows

    def test_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root / "a", self.requests(slow_after=60))
            fault = {"id": "a", "root_cause": "traffic_surge", "root_causes": ["traffic_surge"], "onset_s": 30}
            self.assertTrue(check_incident(root / "a", fault)["valid"])
            self.write(root / "b", self.requests())
            self.assertFalse(check_incident(root / "b", {**fault, "id": "b"})["valid"])
            healthy = {"id": "b", "root_cause": "healthy", "root_causes": ["healthy"], "onset_s": None}
            self.assertTrue(check_incident(root / "b", healthy)["valid"])
            self.assertFalse(check_incident(root / "a", {**healthy, "id": "a"})["valid"])
            self.write(root / "c", self.requests(slow_after=60), status="failed")
            self.assertFalse(check_incident(root / "c", {**fault, "id": "c"})["valid"])


class CliTests(unittest.TestCase):
    def test_generate_hard_writes_sealed_layout(self):
        with tempfile.TemporaryDirectory() as tmp, patch("builtins.print"):
            out = Path(tmp) / "hard"
            cli_main(["generate-hard", "--capacity-rps", "8", "--out", str(out)])
            self.assertTrue((out / "answers" / "answer_keys.json").exists())
            self.assertEqual(json.loads((out / "study.json").read_text())["capacity_rps"], 8)
            scenarios = json.loads((out / "scenarios.json").read_text())["scenarios"]
            self.assertEqual(len(scenarios), 17)

    def test_simulated_hard_pipeline_scores_compounds(self):
        with tempfile.TemporaryDirectory() as tmp, patch("builtins.print"):
            out = Path(tmp) / "sim"
            cli_main(["simulate", "--hard", "--capacity-rps", "8", "--out", str(out)])
            cli_main(["evaluate", "--study-dir", str(out), "--arms", "rules", "--split", "hard"])
            from servedoctor.scoring import score_study
            board = score_study(out, split="hard")["by_arm"]["rules"]
            self.assertEqual(board["compound_incidents"], 4)
            self.assertEqual(board["incidents"] + board["healthy_controls"], 16)


if __name__ == "__main__":
    unittest.main()
