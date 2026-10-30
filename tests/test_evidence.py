import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from servetune.artifacts import digest, file_hash, seal, verify, write_json
from servetune.config import DEFAULT
from servetune.engine import engine_command
from servetune.evidence import import_dev_baseline
from servetune.quality import score_items


UUID = "GPU-11111111-2222-3333-4444-555555555555"


class BaselineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "original"
        self.source.mkdir()
        self.config = deepcopy(DEFAULT)
        self.config["engine"]["model_revision"] = "a" * 40
        self.hardware = {"status": "pass", "driver_version": "test-driver", "vllm_version": "test-vllm",
                         "gpu": {"uuid": UUID, "name": "test-gpu", "total_memory_mib": 97887,
                                 "compute_capability": "12.0"}}
        self.dev = [{"id": f"dev-{i}", "prompt": f"Question {i}", "answer": "42"} for i in range(150)]
        self.baseline = score_items(self.dev, [
            {"id": row["id"], "text": "#### 41" if i < 12 else "#### 42", "finish_reason": "stop"}
            for i, row in enumerate(self.dev)])
        self.data = {"split_validation": {"dev_sha256": digest(self.dev)},
                     "files": {name: {"path": f"/original/{name}.json", "sha256": name * 10}
                               for name in ("prompts", "dev", "final", "provenance")},
                     "provenance": {"license": "MIT", "seed": 20261030}}
        metadata = {
            "dtype": "bf16", "model_id": self.config["engine"]["model_id"], "model_revision": "a" * 40,
            "tokenizer_revision": "a" * 40, "gpu_uuid": UUID, "vllm_version": "test-vllm",
            "baseline_policy": "engine_defaults_under_fixed_context_and_cache_policy",
            "identity_complete": True, "cleanup_status": "completed",
            "argv": engine_command({**self.config["engine"], "gpu_uuid": UUID}, "bf16"),
        }
        report = {"mode": "live", "status": "fail", "config_sha256": digest(self.config),
                  "checks": {"P1": {"status": "fail", "reason": "Later restart failed"},
                             "quality_baseline": {"status": "pass", "evidence": "dev-baseline.json"}}}
        for name, value in (("config.json", self.config), ("hardware.json", self.hardware),
                            ("data-manifest.json", self.data), ("dev-baseline.json", self.baseline),
                            ("quality_gate.json", self.config["quality"]), ("preflight.json", report),
                            ("bf16-1/engine-metadata.json", metadata)):
            write_json(self.source / name, value)
        source_dir = self.source / "source"
        source_dir.mkdir()
        current = Path(__file__).resolve().parents[1] / "servetune"
        for name in ("quality.py", "workload.py", "engine.py", "preflight.py"):
            shutil.copyfile(current / name, source_dir / name)
        seal(self.source)

    def reseal(self):
        (self.source / "manifest.json").unlink()
        seal(self.source)

    def change_json(self, name, change):
        path = self.source / name
        obj = json.loads(path.read_text())
        change(obj)
        path.write_text(json.dumps(obj))
        self.reseal()

    def run_import(self, **overrides):
        arguments = {"config": self.config, "hardware": self.hardware,
                     "dev_items": self.dev, "data_evidence": self.data}
        arguments.update(overrides)
        return import_dev_baseline(self.source, self.root / "imported", **arguments)

    def test_valid_once_measured_reference_survives_later_failed_preflight(self):
        result = self.run_import()
        self.assertEqual(result["baseline"]["correct"], 138)
        self.assertEqual(result["origin"]["original_preflight_status"], "fail")
        self.assertEqual(result["baseline_bytes"], (self.source / "dev-baseline.json").read_bytes())
        self.assertEqual(verify(self.root / "imported/source-run")["status"], "fail")
        self.assertEqual(result["origin"]["source_manifest_sha256"], file_hash(self.source / "manifest.json"))

    def test_data_path_relocation_requires_identical_protocol_and_hashes(self):
        config, data = deepcopy(self.config), deepcopy(self.data)
        for name in config["data"]:
            config["data"][name] = f"/new-host/{name}.json"
            data["files"][name]["path"] = config["data"][name]
        self.assertEqual(self.run_import(config=config, data_evidence=data)["baseline"]["correct"], 138)

    def test_longer_performance_window_preserves_once_measured_quality_reference(self):
        config = deepcopy(self.config)
        config["trace"]["duration_s"] = 480
        imported = self.run_import(config=config)
        self.assertEqual(imported["baseline"]["correct"], 138)
        self.assertEqual(imported["baseline_bytes"], (self.source / "dev-baseline.json").read_bytes())
        window = imported["origin"]["performance_window"]
        self.assertEqual(window["source_trace_duration_s"], 120)
        self.assertEqual(window["current_trace_duration_s"], 480)
        self.assertTrue(window["increased"])
        self.assertIn("quality reference", window["reason"])

    def test_shorter_performance_window_cannot_reuse_reference(self):
        saved = deepcopy(self.config)
        saved["trace"]["duration_s"] = 480
        (self.source / "config.json").write_text(json.dumps(saved))
        report = json.loads((self.source / "preflight.json").read_text())
        report["config_sha256"] = digest(saved)
        (self.source / "preflight.json").write_text(json.dumps(report))
        self.reseal()
        with self.assertRaisesRegex(ValueError, "shorter"):
            self.run_import()  # Current window is the unchanged 120-second default.

    def test_longer_window_does_not_authorize_other_trace_or_protocol_changes(self):
        changes = [("trace", "arrival_rate", 0.2), ("trace", "seed", 20261031),
                   ("trace", "max_output_tokens", 256), ("trace", "max_requests", 128),
                   ("quality", "max_output_tokens", 512),
                   ("engine", "max_model_len", 8192),
                   ("measurement", "warmup_requests", 2)]
        for section, field, value in changes:
            with self.subTest(section=section, field=field):
                config = deepcopy(self.config)
                config["trace"]["duration_s"] = 480
                config[section][field] = value
                with self.assertRaises(ValueError):
                    self.run_import(config=config)
                self.assertFalse((self.root / "imported").exists())

    def test_other_gpu_or_driver_is_rejected(self):
        for field in ("uuid", "driver_version"):
            hardware = deepcopy(self.hardware)
            if field == "uuid":
                hardware["gpu"][field] = "GPU-other"
            else:
                hardware[field] = "different-driver"
            with self.assertRaises(ValueError):
                self.run_import(hardware=hardware)

    def test_protocol_model_and_data_changes_are_rejected(self):
        config = deepcopy(self.config)
        config["engine"]["model_revision"] = "b" * 40
        with self.assertRaises(ValueError):
            self.run_import(config=config)
        config = deepcopy(self.config)
        config["engine"]["max_model_len"] = 8192
        with self.assertRaises(ValueError):
            self.run_import(config=config)
        data = deepcopy(self.data)
        data["files"]["dev"]["sha256"] = "changed"
        with self.assertRaises(ValueError):
            self.run_import(data_evidence=data)

    def test_tampered_seal_is_rejected(self):
        (self.source / "dev-baseline.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.run_import()

    def test_forged_aggregate_resealed_is_rejected(self):
        self.change_json("dev-baseline.json", lambda obj: obj.update(correct=140, incorrect=10, score=140/150))
        with self.assertRaises(ValueError):
            self.run_import()

    def test_forged_per_item_correctness_resealed_is_rejected(self):
        def forge(obj):
            obj["results"][0]["correct"] = True
            obj.update(correct=139, incorrect=11, score=139/150)
        self.change_json("dev-baseline.json", forge)
        with self.assertRaises(ValueError):
            self.run_import()

    def test_saved_scorer_and_engine_identity_are_required(self):
        self.change_json("dev-baseline.json", lambda obj: obj.update(scorer_sha256="changed"))
        with self.assertRaises(ValueError):
            self.run_import()

    def test_engine_argv_change_is_rejected(self):
        self.change_json("bf16-1/engine-metadata.json", lambda obj: obj["argv"].append("--enforce-eager"))
        with self.assertRaises(ValueError):
            self.run_import()

    def test_source_workload_change_is_rejected_even_if_resealed(self):
        path = self.source / "source/workload.py"
        path.write_text(path.read_text() + "\n# changed request implementation\n")
        self.reseal()
        with self.assertRaises(ValueError):
            self.run_import()

    def test_engine_change_is_limited_to_port_availability_probe(self):
        path = self.source / "source/engine.py"
        tree = ast.parse(path.read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ManagedEngine")
        probe = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_port_free")
        probe.body.append(ast.Pass())
        path.write_text(ast.unparse(tree))
        self.reseal()
        self.assertEqual(self.run_import()["baseline"]["correct"], 138)

    def test_engine_change_outside_port_probe_is_rejected(self):
        path = self.source / "source/engine.py"
        path.write_text(path.read_text() + "\nCHANGED_SERVING_POLICY = True\n")
        self.reseal()
        with self.assertRaises(ValueError):
            self.run_import()

    def test_changed_quality_request_function_is_rejected(self):
        path = self.source / "source/preflight.py"
        path.write_text(path.read_text().replace('#### <answer>.', 'Final answer:'))
        self.reseal()
        with self.assertRaises(ValueError):
            self.run_import()

    def test_incomplete_or_imported_reference_cannot_replace_original(self):
        self.change_json("preflight.json", lambda obj: obj["checks"]["quality_baseline"].update(imported=True))
        with self.assertRaises(ValueError):
            self.run_import()


if __name__ == "__main__":
    unittest.main()
