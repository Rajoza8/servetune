import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from servedoctor.cli import main


class EvaluationEngineTests(unittest.TestCase):
    def prepare(self, root):
        (root / "answers").mkdir()
        (root / "answers" / "answer_keys.json").write_text('{"answers": []}')
        study = {"engine_base": {"max_model_len": 4096}, "timing": {"checkpoint_s": 30}}
        (root / "study.json").write_text(json.dumps(study))
        return (root / "study.json").read_bytes()

    def arguments(self, root, split):
        return ["evaluate", "--study-dir", str(root), "--split", split, "--arms", "glimmer",
                "--start-glimmer", "--model-revision", "0" * 40]

    def test_dev_then_test_use_fresh_artifacts_and_sufficient_diagnosis_context(self):
        engines = []

        class Engine:
            def __init__(self, config, path, dtype):
                self.config, self.path = config, path
                self.metadata = {"config": config}
                self.base_url = "http://127.0.0.1:8000/v1"
                self.stopped = False
                engines.append(self)

            def start(self):
                (self.path / "engine.log").open("x").close()

            def stop(self):
                self.stopped = True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen = self.prepare(root)
            with patch("servedoctor.cli._engine_factory", side_effect=Engine), \
                    patch("servedoctor.evaluate.evaluate"):
                self.assertEqual(main(self.arguments(root, "dev")), 0)
                self.assertEqual(main(self.arguments(root, "test")), 0)
            self.assertEqual(len(engines), 2)
            self.assertNotEqual(engines[0].path, engines[1].path)
            for engine in engines:
                self.assertTrue(engine.stopped)
                self.assertGreaterEqual(engine.config["max_model_len"], 5307)
                self.assertTrue((engine.path / "engine_metadata.json").exists())
            self.assertEqual((root / "study.json").read_bytes(), frozen)

    def test_failed_evaluation_start_stops_engine_and_preserves_evidence(self):
        engines = []

        class BrokenEngine:
            def __init__(self, config, path, dtype):
                self.path, self.metadata, self.stopped = path, {"startup": "failed"}, False
                engines.append(self)

            def start(self):
                (self.path / "engine.log").write_text("startup failed")
                raise RuntimeError("simulated startup failure")

            def stop(self):
                self.stopped = True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            with patch("servedoctor.cli._engine_factory", side_effect=BrokenEngine):
                with self.assertRaises(RuntimeError):
                    main(self.arguments(root, "dev"))
            engine = engines[0]
            self.assertTrue(engine.stopped)
            self.assertEqual(json.loads((engine.path / "failure.json").read_text())["error"], "RuntimeError")
            self.assertTrue((engine.path / "engine_metadata.json").exists())


if __name__ == "__main__":
    unittest.main()
