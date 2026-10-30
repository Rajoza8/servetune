import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from servetune.recovery import RecoveryError, build_recovery_bundle


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.output = Path(self.temporary.name) / "recovery.tar.gz"
        self.environment = {"image_digest": "vllm/example@sha256:" + "a" * 64,
                            "packages": {"vllm": "pinned-example"},
                            "HF_TOKEN": "do-not-export-env-token"}
        self.model = {"id": "meta-models/Muse-Glimmer-30B", "sha": "b" * 40,
                      "files": [{"name": "model-00001.safetensors", "size": 60_000_000_000}],
                      "access_token": "do-not-export-model-token"}
        self.put("servetune/__init__.py", "VERSION = 'test'\n")
        self.put("configs/preflight.json", '{"model_revision":"' + "b" * 40 + '"}\n')
        self.put("scripts/run-preflight.sh", "#!/bin/sh\npython3 -m servetune preflight\n")
        self.put("README.md", "# Test project\n")
        self.put("pyproject.toml", "[project]\nname = 'example'\n")
        self.put("BUILD_BRIEF_V4.txt", "Test build brief\n")
        self.put("data/public/provenance.json", '{"license":"MIT","upstream_revision":"pinned"}\n')
        self.put("data/public/LICENSE", "MIT License\n")
        self.put("data/public/dev.json", '[{"id":"dev-1","answer":"42"}]\n')
        self.put("data/public/source/train.jsonl", '{"question":"A?","answer":"1"}\n{"question":"B?","answer":"2"}\n')
        self.put("runs/ledger.json", json.dumps({"project": "servetune", "schema_version": 1,
            "caps_usd": {"meta": "15", "baseten": "5"}, "blocked": False,
            "entries": [{"id": "one", "provider": "meta", "status": "reserved",
                         "reserved_usd": "0.5", "accounted_usd": "0.5",
                         "metadata": {"api_key": "do-not-export-ledger-secret"}}]}) + "\n")
        self.put("runs/preflight-one/preflight.json", '{"status":"blocked","mode":"live"}\n')
        self.put("runs/preflight-one/manifest.json", '{"files":{}}\n')
        self.put("runs/preflight-one/engine.log", "Selected kernel example\n")
        self.run = self.root / "runs/preflight-one"

    def put(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def build(self, **kwargs):
        return build_recovery_bundle(self.root, self.output,
            environment_manifest=self.environment, model_manifest=self.model, **kwargs)

    def members(self):
        with tarfile.open(self.output, "r:gz") as archive:
            self.assertTrue(all(row.isfile() for row in archive.getmembers()))
            return {row.name: archive.extractfile(row).read() for row in archive.getmembers()}

    def test_manifest_hashes_cover_every_exported_payload(self):
        result = self.build(run_paths=[self.run])
        files = self.members()
        manifest = json.loads(files.pop("recovery/file-manifest.json"))
        self.assertEqual(set(manifest["files"]), set(files))
        for name, raw in files.items():
            self.assertEqual(manifest["files"][name]["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(manifest["files"][name]["bytes"], len(raw))
            self.assertFalse(name.startswith("/"))
            self.assertNotIn("..", Path(name).parts)
        self.assertEqual(result["archive_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertFalse(result["weights_included"])
        self.assertIn("MODEL WEIGHTS ARE NOT INCLUDED", files["REBUILD.md"].decode())

    def test_credentials_sessions_and_model_weights_are_excluded(self):
        self.put(".env", "TOP_SECRET=do-not-export-dotenv\n")
        self.put(".env.example", "placeholder\n")
        self.put("servetune/secret_config.py", "PASSWORD = 'do-not-export-source-secret'\n")
        self.put("data/public/model.safetensors", "do-not-export-weights")
        self.put("data/private/unlicensed.json", '{"secret":"do-not-export-private-data"}')
        self.put("runs/ops/session.json", '{"key":"do-not-export-session"}')
        self.put("runs/ops/ssh_ed25519", "do-not-export-private-key")
        self.put("runs/preflight-one/.env", "do-not-export-run-env")
        self.put("runs/preflight-one/ssh_ed25519", "do-not-export-run-key")
        self.put("runs/preflight-one/credentials.json", '{"api_key":"do-not-export-run-credential"}')
        self.build(run_paths=[self.run])
        files = self.members()
        for name, raw in files.items():
            self.assertNotIn(b"do-not-export", raw, name)
            self.assertNotIn(".safetensors", name)
        self.assertFalse(any(name.startswith("project/runs/ops/") for name in files))
        self.assertNotIn("project/data/private/unlicensed.json", files)

    def test_ledger_costs_and_caps_survive_metadata_redaction(self):
        self.build()
        ledger = json.loads(self.members()["project/runs/ledger.json"])
        self.assertEqual(ledger["caps_usd"], {"meta": "15", "baseten": "5"})
        self.assertEqual(ledger["entries"][0]["accounted_usd"], "0.5")
        self.assertEqual(ledger["entries"][0]["status"], "reserved")
        self.assertEqual(ledger["entries"][0]["metadata"]["api_key"], "[REDACTED]")

    def test_default_export_does_not_take_any_run_directory(self):
        self.build()
        self.assertFalse(any(name.startswith("project/runs/preflight-one/") for name in self.members()))
        self.assertIn("project/runs/ledger.json", self.members())

    def test_explicit_preflight_run_is_included_without_neighboring_ops(self):
        self.put("runs/session-neighbor/session.json", '{"host":"do-not-export"}')
        self.build(run_paths=[Path("runs/preflight-one")])
        files = self.members()
        self.assertIn("project/runs/preflight-one/preflight.json", files)
        self.assertIn("project/runs/preflight-one/engine.log", files)
        self.assertNotIn("project/runs/session-neighbor/session.json", files)

    def test_raw_operations_folder_cannot_be_passed_as_a_run(self):
        self.put("runs/operations/session.json", "{}")
        with self.assertRaises(RecoveryError):
            self.build(run_paths=[Path("runs/operations")])
        self.assertFalse(self.output.exists())

    def test_source_and_data_bytes_are_preserved_when_not_sensitive(self):
        self.build(run_paths=[self.run])
        files = self.members()
        for name in ("configs/preflight.json", "data/public/dev.json",
                     "data/public/source/train.jsonl", "runs/preflight-one/preflight.json"):
            self.assertEqual(files["project/" + name], (self.root / name).read_bytes())

    def test_symlinks_are_never_followed_or_archived(self):
        outside = Path(self.temporary.name) / "outside.py"
        outside.write_text("do-not-export-symlink-target")
        (self.root / "servetune/linked.py").symlink_to(outside)
        outside_data = Path(self.temporary.name) / "outside-data"
        outside_data.mkdir()
        (self.root / "data/link").symlink_to(outside_data, target_is_directory=True)
        self.build(run_paths=[self.run])
        files = self.members()
        self.assertNotIn("project/servetune/linked.py", files)
        self.assertFalse(any(b"do-not-export-symlink-target" in raw for raw in files.values()))

    def test_symlink_run_and_traversal_run_are_rejected(self):
        (self.root / "runs/link").symlink_to(self.run, target_is_directory=True)
        for run in (Path("runs/link"), Path("runs/preflight-one/../preflight-one")):
            with self.subTest(run=run):
                with self.assertRaises(RecoveryError):
                    self.build(run_paths=[run])

    def test_existing_archive_is_never_replaced(self):
        self.output.write_bytes(b"keep-existing")
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.output.read_bytes(), b"keep-existing")

    def test_missing_or_symlink_ledger_cannot_silently_reset_allowance(self):
        ledger = self.root / "runs/ledger.json"
        raw = ledger.read_bytes()
        ledger.unlink()
        with self.assertRaises(RecoveryError):
            self.build()
        outside = Path(self.temporary.name) / "outside-ledger.json"
        outside.write_bytes(raw)
        ledger.symlink_to(outside)
        with self.assertRaises(RecoveryError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_per_file_and_total_limits_fail_without_leaving_an_archive(self):
        with patch("servetune.recovery.MAX_FILE_BYTES", 100):
            with self.assertRaises(RecoveryError):
                self.build()
        self.assertFalse(self.output.exists())
        with patch("servetune.recovery.MAX_TOTAL_BYTES", 100):
            with self.assertRaises(RecoveryError):
                self.build()
        self.assertFalse(self.output.exists())

    def test_sensitive_log_values_are_redacted(self):
        self.put("runs/preflight-one/engine.log",
                 "HF_TOKEN=do-not-export-log-token\nAuthorization: Bearer do-not-export-bearer\n"
                 "https://user:do-not-export-password@example.test/file\n")
        self.build(run_paths=[self.run])
        log = self.members()["project/runs/preflight-one/engine.log"].decode()
        self.assertNotIn("do-not-export", log)
        self.assertIn("[REDACTED]", log)


if __name__ == "__main__":
    unittest.main()
