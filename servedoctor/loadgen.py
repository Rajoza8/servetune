"""Open-loop load generator behind a small gateway whose policy can change live.

The gateway is simulated in-process: it admits or sheds each request before it
reaches vLLM. Latency is measured from the scheduled arrival, so client-side
queueing counts.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
import urllib.error

from servetune.workload import completion, percentile


class Gateway:
    def __init__(self, max_rps=None, max_prompt_tokens=None, clock=time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock
        self._max_rps = max_rps
        self._max_prompt_tokens = max_prompt_tokens
        self._tokens = 0.0
        self._last = None

    def policy(self):
        with self._lock:
            return {"max_rps": self._max_rps, "max_prompt_tokens": self._max_prompt_tokens}

    def set_policy(self, *, max_rps=..., max_prompt_tokens=...):
        with self._lock:
            if max_rps is not ...:
                self._max_rps = max_rps
                self._tokens = max_rps or 0.0
                self._last = None
            if max_prompt_tokens is not ...:
                self._max_prompt_tokens = max_prompt_tokens

    def admit(self, prompt_tokens_est):
        with self._lock:
            if self._max_prompt_tokens is not None and prompt_tokens_est > self._max_prompt_tokens:
                return False, "prompt_too_long"
            if self._max_rps is None:
                return True, None
            now = self._clock()
            if self._last is not None:
                self._tokens = min(self._max_rps, self._tokens + (now - self._last) * self._max_rps)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True, None
            return False, "rate_limited"


def http_request(base_url, row, timeout_s):
    """One streamed chat completion; returns a normalized outcome dict."""
    try:
        result = completion(base_url, row["prompt"], row["max_tokens"], timeout_s)
        return {"status": "ok", "ttft_from_dispatch_s": result["ttft_from_dispatch_s"],
                "prompt_tokens": result["usage"]["prompt_tokens"],
                "completion_tokens": result["usage"]["completion_tokens"],
                "finish_reason": result["finish_reason"]}
    except urllib.error.HTTPError as exc:
        return {"status": f"http_{exc.code}"}
    except (TimeoutError, urllib.error.URLError) as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason):
            return {"status": "timeout"}
        return {"status": "connection_error"}
    except Exception as exc:
        return {"status": "error", "error_class": type(exc).__name__}


class LoadGenerator:
    def __init__(self, arrivals, gateway, request_fn, *, clock=time.monotonic, sleeper=time.sleep,
                 max_workers=1024):
        self.arrivals = arrivals
        self.gateway = gateway
        self.request_fn = request_fn
        self.clock, self.sleeper = clock, sleeper
        self.max_workers = max_workers
        self.outcomes = []
        self._window = []
        self._window_arrivals = []
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self.start_time = None
        self._pool = None
        self._futures = []

    def _record_arrival(self, row, admitted, reason):
        with self._lock:
            self._window_arrivals.append((row["prompt_tokens_est"], admitted, reason))

    def _finish(self, record):
        with self._lock:
            self.outcomes.append(record)
            self._window.append(record)

    def _serve(self, row, scheduled):
        dispatched = self.clock()
        result = self.request_fn(row)
        done = self.clock()
        record = {"id": row["id"], "cls": row["cls"], "t_sched": row["t"],
                  "prompt_tokens_est": row["prompt_tokens_est"], **result,
                  "latency_s": done - scheduled, "t_done": done - self.start_time}
        if "ttft_from_dispatch_s" in result:
            record["ttft_s"] = dispatched - scheduled + result.pop("ttft_from_dispatch_s")
            record.pop("ttft_from_dispatch_s", None)
        self._finish(record)

    def _dispatch(self):
        for row in self.arrivals:
            if self._stop.is_set():
                break
            scheduled = self.start_time + row["t"]
            delay = scheduled - self.clock()
            if delay > 0 and self._stop.wait(delay):
                break
            admitted, reason = self.gateway.admit(row["prompt_tokens_est"])
            self._record_arrival(row, admitted, reason)
            if not admitted:
                self._finish({"id": row["id"], "cls": row["cls"], "t_sched": row["t"],
                              "prompt_tokens_est": row["prompt_tokens_est"], "status": "shed",
                              "shed_reason": reason, "latency_s": 0.0,
                              "t_done": self.clock() - self.start_time})
                continue
            self._futures.append(self._pool.submit(self._serve, row, scheduled))

    def start(self, start_time=None):
        self.start_time = self.clock() if start_time is None else start_time
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers)
        self._thread = threading.Thread(target=self._dispatch, name="servedoctor-loadgen", daemon=True)
        self._thread.start()
        return self

    def wait(self, drain_timeout_s=90):
        self._thread.join()
        deadline = self.clock() + drain_timeout_s
        for future in list(self._futures):
            remaining = deadline - self.clock()
            if remaining <= 0:
                break
            try:
                future.result(timeout=remaining)
            except Exception:
                pass
        self._pool.shutdown(wait=False, cancel_futures=True)

    def stop(self):
        self._stop.set()

    def drain_window(self):
        """Summarize outcomes and arrivals since the previous call (one telemetry second)."""
        with self._lock:
            window, arrivals = self._window, self._window_arrivals
            self._window, self._window_arrivals = [], []
        ok = [r for r in window if r["status"] == "ok"]
        errors = {}
        for r in window:
            if r["status"] not in ("ok", "shed"):
                errors[r["status"]] = errors.get(r["status"], 0) + 1
        return {
            "arrivals": len(arrivals),
            "admitted": sum(1 for _, admitted, _ in arrivals if admitted),
            "shed": sum(1 for _, admitted, _ in arrivals if not admitted),
            "arrival_prompt_tokens_est_mean": (sum(t for t, _, _ in arrivals) / len(arrivals)) if arrivals else None,
            "completed_ok": len(ok),
            "errors": errors,
            "latencies_s": [round(r["latency_s"], 3) for r in ok],
            "ttfts_s": [round(r["ttft_s"], 3) for r in ok if "ttft_s" in r],
            "completion_tokens": sum(r.get("completion_tokens", 0) for r in ok),
        }


def summarize(outcomes, start_s=0.0, end_s=float("inf")):
    rows = [r for r in outcomes if start_s <= r["t_sched"] < end_s]
    ok = [r for r in rows if r["status"] == "ok"]
    shed = [r for r in rows if r["status"] == "shed"]
    failed = [r for r in rows if r["status"] not in ("ok", "shed")]
    admitted = len(rows) - len(shed)
    return {"requests": len(rows), "ok": len(ok), "shed": len(shed), "failed": len(failed),
            "shed_rate": len(shed) / len(rows) if rows else 0.0,
            "error_rate": len(failed) / admitted if admitted else 0.0,
            "p50_latency_s": percentile([r["latency_s"] for r in ok], 0.5),
            "p95_latency_s": percentile([r["latency_s"] for r in ok], 0.95)}
