"""The committed live-demo call records reproduce from the repo and re-score to their stored results."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "results" / "live-demo-20261104"


@unittest.skipUnless(RECORDS.exists(), "live-demo records not present")
class LiveDemoRecordTests(unittest.TestCase):
    def test_prompts_reproduce_and_replies_rescore(self):
        spec = importlib.util.spec_from_file_location("verify_live_demo", ROOT / "scripts" / "verify_live_demo.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        checked, problems = module.verify(RECORDS)
        self.assertEqual(problems, [])
        self.assertEqual(checked, 32)


if __name__ == "__main__":
    unittest.main()
