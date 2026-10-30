from pathlib import Path
import errno
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from servetune.engine import EngineError, ManagedEngine, engine_command


CONFIG = {"model_id": "meta-models/Muse-Glimmer-30B", "model_revision": "a" * 40}


class EngineTests(unittest.TestCase):
    def test_fixed_command_pins_model_tokenizer_and_seed(self):
        command = engine_command(CONFIG)
        self.assertEqual(command[:3], ["vllm", "serve", CONFIG["model_id"]])
        self.assertEqual(command[command.index("--revision") + 1], "a" * 40)
        self.assertEqual(command[command.index("--tokenizer-revision") + 1], "a" * 40)
        self.assertIn("--no-enable-prefix-caching", command)
        self.assertNotIn("--trust-remote-code", command)

    def test_fp8_route_is_explicit(self):
        command = engine_command(CONFIG, "fp8")
        self.assertEqual(command[command.index("--quantization") + 1], "fp8_per_tensor")

    def test_default_baseline_omits_tuning_overrides(self):
        config = {**CONFIG, "use_engine_defaults": True}
        command = engine_command(config)
        for flag in ("--max-num-seqs", "--max-num-batched-tokens", "--gpu-memory-utilization",
                     "--enable-chunked-prefill", "--no-enable-chunked-prefill"):
            self.assertNotIn(flag, command)
        self.assertIn("--max-model-len", command)
        self.assertIn("--no-enable-prefix-caching", command)
        with tempfile.TemporaryDirectory() as directory:
            engine = ManagedEngine(config, Path(directory))
            self.assertIsNone(engine.metadata["requested_tuning_values"])
            self.assertIsNone(engine.metadata["effective_tuning_values"])
            self.assertEqual(engine.metadata["baseline_policy"], "engine_defaults_under_fixed_context_and_cache_policy")

    def test_observed_1024_sequence_default_fits_bound_without_changing_default_argv(self):
        config = {**CONFIG, "max_num_seqs": 1024}
        command = engine_command(config)
        self.assertEqual(command[command.index("--max-num-seqs") + 1], "1024")
        self.assertEqual(engine_command({**config, "use_engine_defaults": True}),
                         engine_command({**CONFIG, "use_engine_defaults": True}))
        with self.assertRaises(ValueError):
            engine_command({**CONFIG, "max_num_seqs": 1025})

    def test_model_must_be_pinned(self):
        for revision in ("main", "", None, "a" * 39):
            with self.assertRaises(ValueError):
                engine_command({**CONFIG, "model_revision": revision})

    def test_unknown_settings_and_shell_shaped_values_are_rejected(self):
        changes = ({"extra_flags": "--bad"}, {"host": "0.0.0.0"},
                   {"engine_executable": "sh"}, {"model_id": "--bad"},
                   {"max_num_seqs": True}, {"gpu_memory_utilization": float("nan")},
                   {"gpu_memory_utilization": 1.0}, {"enable_chunked_prefill": "false"},
                   {"gpu_uuid": "0"}, {"use_engine_defaults": "true"})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                engine_command({**CONFIG, **change})

    @patch("servetune.engine.subprocess.Popen")
    def test_occupied_port_is_not_attached_or_killed(self, popen):
        for reuseaddr in (False, True):
            with self.subTest(reuseaddr=reuseaddr), tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, int(reuseaddr))
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                port = listener.getsockname()[1]
                engine = ManagedEngine({**CONFIG, "port": port}, Path(directory))
                with self.assertRaises(EngineError):
                    engine.start()
                engine.stop()
                popen.assert_not_called()
                self.assertEqual(listener.getsockname()[1], port)

    def test_port_precheck_accepts_time_wait_from_completed_engine(self):
        # A real server-side active close leaves TIME_WAIT even after its
        # listener exits. A bare bind rejects this otherwise reusable port.
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.settimeout(2)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            address = listener.getsockname()
            with socket.socket() as client:
                client.settimeout(2)
                client.connect(address)
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(2)
                    connection.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b"")
                    client.shutdown(socket.SHUT_WR)
                    self.assertEqual(connection.recv(1), b"")
        with socket.socket() as bare_check:
            with self.assertRaises(OSError) as caught:
                bare_check.bind(address)
            self.assertEqual(caught.exception.errno, errno.EADDRINUSE)
        with tempfile.TemporaryDirectory() as directory:
            engine = ManagedEngine({**CONFIG, "port": address[1]}, Path(directory))
            engine._port_free()

    @patch("servetune.engine.os.killpg")
    @patch("servetune.engine.ManagedEngine._owned_group_state", side_effect=["owned", "absent", "absent"])
    @patch("servetune.engine.ManagedEngine._health", return_value=True)
    @patch("servetune.engine.subprocess.Popen")
    def test_success_owns_and_stops_its_process_group(self, popen, health, group_state, killpg):
        process = MagicMock()
        process.pid = 43210
        process.poll.return_value = None
        process.returncode = 0
        popen.return_value = process
        with tempfile.TemporaryDirectory() as directory:
            engine = ManagedEngine({**CONFIG, "gpu_uuid": "GPU-123"}, Path(directory))
            with patch.dict("os.environ", {"META_API_KEY": "secret", "MODEL_API_KEY": "secret2"}):
                engine.start()
            call = popen.call_args
            self.assertTrue(call.kwargs["start_new_session"])
            self.assertNotIn("shell", call.kwargs)
            self.assertNotIn("META_API_KEY", call.kwargs["env"])
            self.assertNotIn("MODEL_API_KEY", call.kwargs["env"])
            self.assertEqual(call.kwargs["env"]["CUDA_VISIBLE_DEVICES"], "GPU-123")
            engine.stop()
            killpg.assert_called_once()
            self.assertEqual(killpg.call_args.args[0], process.pid)
            self.assertEqual(engine.metadata["owned_pid"], process.pid)
            self.assertFalse(engine.metadata["identity_complete"])

    @patch("servetune.engine.os.killpg")
    def test_workers_are_cleaned_even_after_leader_exits(self, killpg):
        with tempfile.TemporaryDirectory() as directory:
            engine = ManagedEngine(CONFIG, Path(directory))
            engine._process = MagicMock(pid=43210, returncode=1)
            engine._process.poll.return_value = 1
            engine._owned_pgid = engine._owned_session = 43210
            with patch.object(engine, "_owned_group_state", side_effect=["owned", "absent", "absent"]):
                engine.stop()
            killpg.assert_called_once()
            self.assertEqual(killpg.call_args.args[0], 43210)
            self.assertEqual(engine.metadata["cleanup_status"], "completed")

    @patch("servetune.engine.os.killpg")
    def test_unverified_recycled_group_is_never_signalled(self, killpg):
        with tempfile.TemporaryDirectory() as directory:
            engine = ManagedEngine(CONFIG, Path(directory))
            engine._process = MagicMock(pid=43210, returncode=1)
            engine._process.poll.return_value = 1
            engine._owned_pgid = engine._owned_session = 43210
            with patch.object(engine, "_owned_group_state", return_value="unverified"):
                with self.assertRaises(EngineError):
                    engine.stop()
            killpg.assert_not_called()
            self.assertEqual(engine.metadata["cleanup_status"], "failed")

    def test_orphan_ownership_requires_session_and_inherited_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = ManagedEngine(CONFIG, Path(directory) / "artifacts")
            engine._owned_pgid = engine._owned_session = 43210
            engine._proc_root = Path(directory) / "proc"
            member = engine._proc_root / "43211"
            member.mkdir(parents=True)
            (member / "stat").write_text("43211 (vllm worker) S 1 43210 43210 0\n")
            (member / "environ").write_bytes(b"SERVETUNE_ENGINE_OWNER=some-other-engine\0")
            self.assertEqual(engine._owned_group_state(), "unverified")
            (member / "environ").write_bytes(f"SERVETUNE_ENGINE_OWNER={engine._owner_marker}\0".encode())
            self.assertEqual(engine._owned_group_state(), "owned")
            (member / "stat").write_text("43211 (vllm worker) S 1 43210 99999 0\n")
            self.assertEqual(engine._owned_group_state(), "unverified")

    @patch("servetune.engine.subprocess.Popen", side_effect=FileNotFoundError)
    def test_missing_engine_preserves_log_and_closes_handle(self, popen):
        with tempfile.TemporaryDirectory() as directory:
            engine = ManagedEngine(CONFIG, Path(directory))
            with self.assertRaises(FileNotFoundError):
                engine.start()
            self.assertTrue((Path(directory) / "engine.log").is_file())
            self.assertIsNone(engine._log)

    def test_backend_identity_is_evidence_not_requested_dtype(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "engine.log").write_text("Selected CUTLASS for linear\nModel loading took 60 GiB\n")
            engine = ManagedEngine(CONFIG, path, "fp8")
            engine._read_log_metadata()
            self.assertIn("CUTLASS", engine.metadata["kernel_backend_lines"][0])
            self.assertTrue(engine.metadata["memory_footprint_lines"])
            self.assertEqual(engine.metadata["dtype"], "fp8")
