import copy
import json
from pathlib import Path
import tempfile
import unittest

from servetune.artifacts import verify as _unused  # noqa: F401  (ServeTune untouched)
from servedoctor import catalog, scenarios
from servedoctor.fakeserve import FakeServer
from servedoctor.loadgen import Gateway
from servedoctor.record import record_study
from servedoctor.telemetry import parse_prometheus, read_jsonl

STUDY = json.loads((Path(__file__).resolve().parents[1] / "configs" / "servedoctor.json").read_text())
QUESTIONS = [f"Question {i}: a farmer has {i} apples and buys {i + 3} more. How many now?" for i in range(400)]


def small_study():
    study = copy.deepcopy(STUDY)
    study["capacity_rps"] = 20
    study["timing"] = {"pre_onset_s": 2, "fault_s": 2, "checkpoint_s": 1, "settle_s": 1}
    study["prompt_tokens"] = {"medium": [700, 900], "long": [1500, 2000]}
    return study


class CatalogTests(unittest.TestCase):
    def test_validate_and_judge(self):
        config = {"max_num_seqs": 4, "gpu_memory_utilization": 0.76, "max_model_len": 768}
        up = catalog.validate_action({"type": "set_engine_config", "knob": "max_num_seqs", "value": 64},
                                     current_config=config)
        down = catalog.validate_action({"type": "set_engine_config", "knob": "max_num_seqs", "value": 2},
                                       current_config=config)
        self.assertTrue(catalog.judge_actions("batch_limit_too_low", [up], current_config=config)["fixes"])
        self.assertTrue(catalog.judge_actions("batch_limit_too_low", [down], current_config=config)["harmful"])
        limit = catalog.validate_action({"type": "gateway_rate_limit", "max_rps": 3})
        self.assertTrue(catalog.judge_actions("healthy", [limit], current_config=config)["harmful"])
        noop = catalog.validate_action({"type": "no_action"})
        verdict = catalog.judge_actions("healthy", [noop], current_config=config)
        self.assertTrue(verdict["fixes"])
        self.assertFalse(verdict["harmful"])
        stop = catalog.validate_action({"type": "stop_gpu_process", "pid": 4242})
        self.assertTrue(catalog.judge_actions("gpu_contention", [stop], current_config=config,
                                              contention_pids=[4242])["fixes"])
        self.assertTrue(catalog.judge_actions("gpu_contention", [stop], current_config=config,
                                              contention_pids=[9])["harmful"])
        with self.assertRaises(catalog.ActionError):
            catalog.validate_action({"type": "shell", "cmd": "rm -rf /"})
        with self.assertRaises(catalog.ActionError):
            catalog.validate_action({"type": "set_engine_config", "knob": "tensor_parallel_size", "value": 2})


class ScenarioTests(unittest.TestCase):
    def test_generation_is_deterministic_and_hides_labels(self):
        study = small_study()
        first, keys = scenarios.generate(study)
        second, _ = scenarios.generate(study)
        self.assertEqual(first, second)
        self.assertEqual(len(keys), 6 * 3 + 2 + 4)
        self.assertEqual(sum(1 for k in keys if k["split"] == "dev"), 8)
        public = json.dumps(first)
        for cause in catalog.INCIDENT_CAUSES:
            self.assertNotIn(cause, public)
        self.assertTrue(all(any(e["kind"] == "deploy" and e["t"] == 0 for e in s["events"]) for s in first))
        self.assertEqual(first[-1]["id"], "reference")

    def test_requires_calibration(self):
        with self.assertRaises(ValueError):
            scenarios.generate(STUDY)

    def test_arrivals_follow_schedule(self):
        study = small_study()
        pools = scenarios.build_prompt_pools(QUESTIONS, study["prompt_tokens"], 1, per_class=8)
        scenario = {"schedule": [scenarios._phase(0, 5, {"short": 1.0}),
                                 scenarios._phase(10, 50, {"long": 1.0})],
                    "duration_s": 20, "workload_seed": 3, "max_output_tokens": 16}
        rows = scenarios.make_arrivals(scenario, pools)
        early = [r for r in rows if r["t"] < 10]
        late = [r for r in rows if r["t"] >= 10]
        self.assertGreater(len(late), 4 * len(early))
        self.assertTrue(all(r["cls"] == "long" for r in late))


class GatewayTests(unittest.TestCase):
    def test_rate_limit_and_prompt_cap(self):
        now = [0.0]
        gateway = Gateway(clock=lambda: now[0])
        self.assertEqual(gateway.admit(10), (True, None))
        gateway.set_policy(max_rps=2)
        admitted = 0
        for _ in range(20):
            now[0] += 0.1
            admitted += gateway.admit(10)[0]
        self.assertLessEqual(admitted, 6)
        gateway.set_policy(max_rps=None, max_prompt_tokens=50)
        self.assertEqual(gateway.admit(60), (False, "prompt_too_long"))


class PrometheusTests(unittest.TestCase):
    def test_aliases_and_histograms(self):
        text = "\n".join(['vllm:num_requests_running{a="1"} 3', 'vllm:num_requests_running{a="2"} 2',
                          'vllm:gpu_cache_usage_perc{a="1"} 0.5', 'vllm:e2e_request_latency_seconds_sum 9',
                          'vllm:e2e_request_latency_seconds_count 3', 'vllm:e2e_request_latency_seconds_bucket{le="1"} 1',
                          'other_metric 7'])
        row = parse_prometheus(text)
        self.assertEqual(row["running"], 5)
        self.assertEqual(row["kv_usage"], 50)
        self.assertEqual(row["e2e_count"], 3)
        self.assertNotIn("other_metric", row)


class RecordTests(unittest.TestCase):
    def test_record_against_fake_engine(self):
        study = small_study()
        scenario_list, keys = scenarios.generate(study)
        pools = scenarios.build_prompt_pools(QUESTIONS, study["prompt_tokens"], 2, per_class=8)
        context = next(k for k in keys if k["root_cause"] == "context_limit_too_small" and k["severity_index"] == 2)
        healthy = next(k for k in keys if k["root_cause"] == "healthy")
        with tempfile.TemporaryDirectory() as tmp:
            serving = {"model_id": "fake/fake", "model_revision": "0" * 40, "port": 8000}
            results = record_study(scenario_list, serving=serving, pools=pools, out_dir=tmp,
                                   engine_factory=lambda config, path, dtype: FakeServer(config, path, dtype),
                                   ids={context["id"], healthy["id"]}, log=lambda *_: None,
                                   drain_timeout_s=10)
            self.assertEqual(len(results), 2)
            inc = Path(tmp) / "incidents" / healthy["id"]
            rows = read_jsonl(inc / "telemetry.jsonl")
            self.assertGreaterEqual(len(rows), 3)
            self.assertIn("running", rows[-1]["vllm"])
            self.assertIn("arrivals", rows[0]["client"])
            self.assertTrue((inc / "manifest.json").exists())
            for name in ("scenarios.json", "answer_keys.json"):
                self.assertFalse((inc / name).exists())
            requests = read_jsonl(Path(tmp) / "incidents" / context["id"] / "requests.jsonl")
            self.assertTrue(any(r["status"] == "http_400" for r in requests))


if __name__ == "__main__":
    unittest.main()
