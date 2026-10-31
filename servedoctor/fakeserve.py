"""A tiny fake vLLM (OpenAI streaming + /metrics) for offline tests and rehearsals.

It models a sequence limit, per-token decode time and a context limit, so the
recorder, gateway and live loop can be exercised without a GPU. Never use its
output as evidence: everything it produces is synthetic.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

from .scenarios import estimate_tokens


class FakeEngine:
    def __init__(self, *, max_num_seqs=8, max_model_len=4096, token_s=0.002, slowdown=1.0):
        self.max_num_seqs, self.max_model_len = max_num_seqs, max_model_len
        self.token_s, self.slowdown = token_s, slowdown
        self.slots = threading.Semaphore(max_num_seqs)
        self.lock = threading.Lock()
        self.running = self.waiting = 0
        self.success = self.prompt_tokens = self.generation_tokens = 0
        self.ttft_sum = self.ttft_count = 0.0

    def metrics(self):
        with self.lock:
            return "\n".join([
                "# HELP vllm:num_requests_running Running",
                f'vllm:num_requests_running{{model_name="fake"}} {self.running}',
                f'vllm:num_requests_waiting{{model_name="fake"}} {self.waiting}',
                f'vllm:kv_cache_usage_perc{{model_name="fake"}} {min(1.0, self.running / self.max_num_seqs):.3f}',
                f'vllm:num_preemptions_total{{model_name="fake"}} 0',
                f'vllm:prompt_tokens_total{{model_name="fake"}} {self.prompt_tokens}',
                f'vllm:generation_tokens_total{{model_name="fake"}} {self.generation_tokens}',
                f'vllm:request_success_total{{finished_reason="stop"}} {self.success}',
                f'vllm:time_to_first_token_seconds_sum{{model_name="fake"}} {self.ttft_sum}',
                f'vllm:time_to_first_token_seconds_count{{model_name="fake"}} {self.ttft_count}',
                f'vllm:time_to_first_token_seconds_bucket{{le="1.0"}} {self.ttft_count}', ""])


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _json(self, code, body):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/v1/models":
                self._json(200, {"data": [{"id": "servetune-glimmer"}]})
            elif self.path == "/metrics":
                raw = engine.metrics().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                self._json(404, {})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            prompt = body["messages"][-1]["content"]
            prompt_tokens = estimate_tokens(prompt)
            max_tokens = body["max_tokens"]
            if prompt_tokens + max_tokens > engine.max_model_len:
                self._json(400, {"error": "maximum context length exceeded"})
                return
            queued = time.monotonic()
            with engine.lock:
                engine.waiting += 1
            engine.slots.acquire()
            with engine.lock:
                engine.waiting -= 1
                engine.running += 1
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                time.sleep(prompt_tokens * engine.token_s * 0.05 * engine.slowdown)
                tokens = min(max_tokens, 8)
                for index in range(tokens):
                    chunk = {"choices": [{"delta": {"content": "x"}, "finish_reason": None}]}
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                    if index == 0:
                        with engine.lock:
                            engine.ttft_sum += time.monotonic() - queued
                            engine.ttft_count += 1
                    time.sleep(engine.token_s * engine.slowdown)
                final = {"choices": [{"delta": {}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": tokens,
                                   "total_tokens": prompt_tokens + tokens}}
                self.wfile.write(b"data: " + json.dumps(final).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
                with engine.lock:
                    engine.success += 1
                    engine.prompt_tokens += prompt_tokens
                    engine.generation_tokens += tokens
            finally:
                with engine.lock:
                    engine.running -= 1
                engine.slots.release()
                self.close_connection = True

    return Handler


class FakeServer:
    """Duck-types the parts of ManagedEngine that the recorder and live loop use."""
    def __init__(self, config, artifact_dir, dtype="bf16", **engine_kwargs):
        from pathlib import Path
        self.config = dict(config)
        self.artifact_dir = Path(artifact_dir)
        self.engine = FakeEngine(max_num_seqs=config.get("max_num_seqs", 8),
                                 max_model_len=config.get("max_model_len", 4096), **engine_kwargs)
        self.httpd = None
        self.base_url = None
        self.metadata = {"model_id": "fake", "model_revision": "0" * 40, "vllm_version": "fake",
                         "dtype": dtype, "gpu_uuid": None, "kernel_backend_lines": [], "mode": "synthetic"}

    def start(self):
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        (self.artifact_dir / "engine.log").write_text("INFO fake engine started\n")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.engine))
        self.httpd.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
