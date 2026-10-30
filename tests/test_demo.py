"""Video planning/encoding boundaries, without installs or GPU/API operations."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from servetune.artifacts import digest, seal, write_json
from servetune.demo import (CHAPTERS, DemoDependencyError, _command, _pillow, _resolve_ffmpeg,
                           _srt_time, generate_demo)
from servetune.quality import score_items


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "study"
        self.root.mkdir()
        self.out = self.root.with_name("demo")
        self.index = []
        write_json(self.root / "protocol.json", {"tuning": {"slo_s": 3}})

    def trial(self, name, *, phase="map", mode="live", energy=2, config_label=None, final=False):
        path = self.root / "trials" / name
        trace = {"requests": [{"id": "fixture", "arrival_s": 0}]}
        config = {"max_num_seqs": 64}
        quality = None
        if final:
            items = [{"id": f"q-{i}", "answer": "42"} for i in range(300)]
            quality = score_items(items, [{"id": item["id"], "text": "#### 42", "finish_reason": "stop"} for item in items])
        write_json(path / "trial.json", {"mode": mode, "status": "pass", "config": config,
            "config_sha256": digest(config), "trace_sha256": digest(trace), "dtype": "fp8" if "fp8" in name else "bf16",
            "hardware": {"gpu": {"uuid": "GPU-fixture"}}, "quality": quality,
            "measurement": {"joules": energy*100, "generated_tokens": 100,
                "joules_per_output_token": energy, "joules_per_completed_request": energy*100,
                "p95_latency_s": .5, "p95_ttft_s": .1, "completed_requests": 1,
                "scheduled_requests": 1, "all_requests_completed": True}})
        write_json(path / "trace.json", trace)
        seal(path)
        self.index.append({"id": name, "path": f"trials/{name}", "phase": phase,
                           "config_label": config_label or name, "load_label": "load-1"})

    def finish(self, *, mode="live", sealed=True, status="complete"):
        write_json(self.root / "study.json", {"mode": mode, "status": status, "trials": self.index})
        if sealed:
            seal(self.root)

    def test_default_storyboard_is_exactly_180_seconds_in_six_declared_chapters(self):
        self.trial("fixture", mode="synthetic_fixture")
        self.finish(mode="synthetic_fixture")
        result = generate_demo(self.root, self.out, render=False)
        plan = json.loads(Path(result["storyboard"]).read_text())
        self.assertEqual(plan["duration_s"], 180)
        self.assertEqual(len(plan["chapters"]), 6)
        self.assertEqual([round(row["end_s"]-row["start_s"]) for row in plan["chapters"]], [20,25,35,25,50,25])
        self.assertEqual(plan["chapters"][-1]["end_s"], 180)
        self.assertIn("00:03:00,000", Path(result["captions"]).read_text())
        self.assertEqual(result["render_status"], "not_requested")
        self.assertIsNone(result["video"])

    def test_synthetic_video_never_promotes_fixture_numbers_as_headline(self):
        self.trial("fake-confirmation", phase="confirmation", mode="synthetic_fixture", energy=99999, final=True)
        self.finish(mode="synthetic_fixture")
        result = generate_demo(self.root, self.out, render=False)
        plan = json.loads(Path(result["storyboard"]).read_text())
        self.assertTrue(plan["synthetic"])
        self.assertFalse(plan["result_ready"])
        self.assertEqual(plan["confirmed_groups"], {})
        script = Path(result["script"]).read_text()
        self.assertIn("SYNTHETIC SOFTWARE DEMO", script)
        self.assertNotIn("99999", script)

    def test_only_fresh_confirmation_numbers_enter_result_narration(self):
        self.trial("tuning", phase="search", energy=.001)
        self.trial("bf16", phase="confirmation", config_label="bf16-default", energy=2, final=True)
        self.trial("fp8", phase="confirmation", config_label="fp8-default", energy=3, final=True)
        self.finish()
        result = generate_demo(self.root, self.out, render=False)
        plan = json.loads(Path(result["storyboard"]).read_text())
        self.assertTrue(plan["result_ready"])
        self.assertEqual(plan["confirmed_groups"]["bf16-default"]["joules_per_output_token"], 2)
        self.assertEqual(plan["confirmed_groups"]["fp8-default"]["joules_per_output_token"], 3)
        script = Path(result["script"]).read_text()
        self.assertIn("median of 2 GPU joules", script)
        self.assertNotIn("0.001", script)
        self.assertIn("no assumed positive saving", script)

    def test_incomplete_checkpoint_is_a_process_demo_with_no_result_claim(self):
        self.trial("search", phase="search", energy=.001)
        self.finish(sealed=False, status="partial")
        result = generate_demo(self.root, self.out, render=False)
        self.assertFalse(result["result_ready"])
        self.assertIn("INCOMPLETE PROCESS DEMO", Path(result["script"]).read_text())
        self.assertIn("not a final optimization result", Path(result["script"]).read_text())

    def test_missing_ffmpeg_preserves_narration_and_captions(self):
        self.trial("map")
        self.finish()
        with patch("servetune.demo._resolve_ffmpeg", side_effect=DemoDependencyError("No local ffmpeg")):
            result = generate_demo(self.root, self.out)
        self.assertEqual(result["render_status"], "dependency_unavailable")
        self.assertTrue(Path(result["script"]).is_file())
        self.assertTrue(Path(result["captions"]).is_file())
        self.assertIsNone(result["video"])

    def test_missing_pillow_preserves_scripts_without_starting_an_encoder(self):
        self.trial("map")
        self.finish()
        with patch("servetune.demo._resolve_ffmpeg", return_value="/local/ffmpeg"), \
             patch("servetune.demo._pillow", side_effect=DemoDependencyError("No Pillow")), \
             patch("servetune.demo.subprocess.Popen") as process:
            result = generate_demo(self.root, self.out)
        self.assertEqual(result["render_status"], "dependency_unavailable")
        process.assert_not_called()
        self.assertTrue(Path(result["storyboard"]).is_file())

    def test_fixed_encoder_argv_treats_audio_and_output_as_literal_paths(self):
        output = Path(self.temporary.name) / "video $(touch nope).mp4"
        audio = Path(self.temporary.name) / "audio; echo nope.aiff"
        args = _command("/usr/bin/ffmpeg", output, 180, audio=audio)
        self.assertEqual(args[0], "/usr/bin/ffmpeg")
        self.assertEqual(args[-1], str(output))
        self.assertIn(str(audio), args)
        self.assertEqual(args[args.index("-t")+1], "180")
        self.assertIn("libx264", args)
        self.assertIn("yuv420p", args)
        self.assertNotIn("-y", args)
        self.assertTrue(all(isinstance(value, str) for value in args))

    def test_arbitrary_shell_executable_cannot_be_used_as_ffmpeg(self):
        executable = Path(self.temporary.name) / "sh"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        with self.assertRaises(DemoDependencyError):
            _resolve_ffmpeg(executable)

    def test_verified_source_is_unchanged_and_existing_video_not_overwritten(self):
        self.trial("map")
        self.finish()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        generate_demo(self.root, self.out, render=False)
        (self.out / "servetune-demo.mp4").write_bytes(b"keep existing")
        with self.assertRaises(FileExistsError):
            generate_demo(self.root, self.out)
        self.assertEqual((self.out / "servetune-demo.mp4").read_bytes(), b"keep existing")
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        with self.assertRaises(ValueError):
            generate_demo(self.root, self.root / "demo", render=False)

    def test_invalid_duration_is_rejected_before_writing(self):
        for duration in (0, -1, 1.5, True, 601):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    generate_demo(self.root, self.out, duration_s=duration, render=False)
        self.assertFalse(self.out.exists())

    def test_srt_time_rounding_is_stable(self):
        self.assertEqual(_srt_time(180), "00:03:00,000")
        self.assertEqual(_srt_time(1.234), "00:00:01,234")

    def test_one_second_real_encoder_smoke_when_local_dependencies_exist(self):
        try:
            binary = _resolve_ffmpeg()
            _pillow()
        except DemoDependencyError as exc:
            self.skipTest(str(exc))
        self.trial("map")
        self.finish()
        result = generate_demo(self.root, self.out, ffmpeg=binary, duration_s=1)
        self.assertEqual(result["render_status"], "rendered", result.get("error"))
        self.assertIn(b"ftyp", Path(result["video"]).read_bytes()[:64])
        self.assertEqual(result["ffmpeg_argv"][result["ffmpeg_argv"].index("-t")+1], "1")


if __name__ == "__main__":
    unittest.main()
