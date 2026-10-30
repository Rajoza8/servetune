import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from servetune.data import COMMIT_URL, MAX_DOWNLOAD_BYTES, RAW_ROOT, DatasetError, prepare_gsm8k


REVISION = "a" * 40
LICENSE = b"MIT License\nCopyright OpenAI\nPermission is hereby granted, free of charge...\n"


def jsonl(split, count):
    return ("\n".join(json.dumps({"question": f"{split} question {index}?",
                                  "answer": f"Calculate something.\n#### {index}.00"})
                     for index in range(count)) + "\n").encode()


def sources():
    return {COMMIT_URL: json.dumps({"sha": REVISION}).encode(),
            f"{RAW_ROOT}/{REVISION}/LICENSE": LICENSE,
            f"{RAW_ROOT}/{REVISION}/grade_school_math/data/train.jsonl": jsonl("train", 200),
            f"{RAW_ROOT}/{REVISION}/grade_school_math/data/test.jsonl": jsonl("test", 350)}


class DataTests(unittest.TestCase):
    def test_freezes_exact_revision_license_indices_and_disjoint_manifests(self):
        data = sources()
        calls = []
        def fetch(url):
            calls.append(url)
            return data[url]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "frozen"
            provenance = prepare_gsm8k(root, transport=fetch)
            dev = json.loads((root / "dev.json").read_text())
            final = json.loads((root / "final.json").read_text())
            prompts = json.loads((root / "prompts.json").read_text())
            self.assertEqual(len(dev), 150)
            self.assertEqual(len(final), 300)
            self.assertEqual(len(prompts), 12)
            self.assertFalse({item["id"] for item in dev} & {item["id"] for item in final})
            self.assertFalse(set(prompts) & {item["prompt"] for item in dev + final})
            self.assertEqual((root / "LICENSE").read_bytes(), LICENSE)
            self.assertEqual(provenance["upstream_revision"], REVISION)
            self.assertEqual(provenance["license"]["spdx"], "MIT")
            self.assertEqual(len(calls), 4)
            for name, checksum in provenance["files_sha256"].items():
                self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), checksum)
            first = dev[0]
            self.assertEqual(int(first["id"].rsplit("-", 1)[1]),
                             provenance["selection"]["dev"]["source_indices_zero_based"][0])
            self.assertEqual(set(first), {"id", "prompt", "answer"})
            self.assertIn("do not load final answers", provenance["final_split_policy"])

    def test_same_seed_has_identical_selections_and_different_seed_changes_them(self):
        data = sources()
        with tempfile.TemporaryDirectory() as directory:
            roots = [Path(directory) / str(i) for i in range(3)]
            for root, seed in zip(roots, [20261030, 20261030, 20261031]):
                prepare_gsm8k(root, seed, transport=data.__getitem__)
            for name in ("prompts.json", "dev.json", "final.json"):
                self.assertEqual((roots[0] / name).read_bytes(), (roots[1] / name).read_bytes())
            self.assertNotEqual((roots[0] / "dev.json").read_bytes(), (roots[2] / "dev.json").read_bytes())

    def test_refuses_existing_directory_without_network_or_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileExistsError):
                prepare_gsm8k(directory, transport=lambda _: self.fail("Unexpected fetch"))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_rejects_unpinned_revision_and_wrong_license(self):
        for replacement in (b'{"sha":"master"}', b'{"sha":"' + b"a" * 40 + b'","sha":"master"}'):
            data = sources()
            data[COMMIT_URL] = replacement
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "frozen"
                with self.assertRaises(DatasetError):
                    prepare_gsm8k(root, transport=data.__getitem__)
                self.assertFalse(root.exists())
        data = sources()
        data[f"{RAW_ROOT}/{REVISION}/LICENSE"] = b"All rights reserved"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DatasetError):
                prepare_gsm8k(Path(directory) / "frozen", transport=data.__getitem__)

    def test_rejects_bad_answer_and_insufficient_unique_questions(self):
        train_url = f"{RAW_ROOT}/{REVISION}/grade_school_math/data/train.jsonl"
        for raw in (b'{"question":"Problem?","answer":"missing final marker"}\n',
                    (json.dumps({"question": "Repeated problem?", "answer": "#### 4"}) + "\n").encode() * 200):
            data = sources()
            data[train_url] = raw
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(DatasetError):
                    prepare_gsm8k(Path(directory) / "frozen", transport=data.__getitem__)

    def test_source_cross_split_duplicates_are_excluded(self):
        data = sources()
        test_url = f"{RAW_ROOT}/{REVISION}/grade_school_math/data/test.jsonl"
        duplicate = json.dumps({"question": "train question 0?", "answer": "#### 0"})
        data[test_url] += (duplicate + "\n").encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "frozen"
            prepare_gsm8k(root, transport=data.__getitem__)
            dev = json.loads((root / "dev.json").read_text())
            final = json.loads((root / "final.json").read_text())
            prompts = json.loads((root / "prompts.json").read_text())
            self.assertFalse({row["prompt"] for row in dev} & {row["prompt"] for row in final})
            self.assertFalse(set(prompts) & {row["prompt"] for row in dev + final})

    def test_bounded_sources_and_seed_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in (True, -1, "20261030", 2**63):
                with self.assertRaises(DatasetError):
                    prepare_gsm8k(Path(directory) / "frozen", value,
                                  transport=lambda _: self.fail("Unexpected fetch"))
            for raw in (b"", "text", b"x" * (MAX_DOWNLOAD_BYTES + 1)):
                with self.assertRaises(DatasetError):
                    prepare_gsm8k(Path(directory) / "frozen", transport=lambda _: raw)


if __name__ == "__main__":
    unittest.main()
