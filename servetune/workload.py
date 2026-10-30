"""Frozen open-loop traces, streaming local requests, and complete-workload energy."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import random
import statistics
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .artifacts import digest, write_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local inference redirect refused")


def make_trace(prompts, settings):
    if not prompts or any(type(p) is not str or not p.strip() for p in prompts):
        raise ValueError("Nonempty prompt strings required")
    rng = random.Random(settings["seed"])
    rows, offset = [], 0.0
    while offset < settings["duration_s"]:
        if len(rows) >= settings["max_requests"]:
            raise ValueError("Trace exceeds max_requests; lower arrival rate instead of silently truncating")
        i = len(rows)
        rows.append({"id": f"request-{i:04d}", "arrival_s": offset,
                     "prompt": prompts[i % len(prompts)], "max_output_tokens": settings["max_output_tokens"]})
        offset += rng.expovariate(settings["arrival_rate"])
    return {"schema_version": 1, "settings": settings, "prompts_sha256": digest(prompts), "requests": rows}


def percentile(values, quantile):
    if not values:
        return None
    rows = sorted(values)
    position = (len(rows) - 1) * quantile
    lo, hi = math.floor(position), math.ceil(position)
    return rows[lo] + (rows[hi] - rows[lo]) * (position - lo)


def coefficient_of_variation(values):
    if len(values) < 3 or any(not math.isfinite(x) or x <= 0 for x in values):
        raise ValueError("Three positive finite repeats required")
    return statistics.stdev(values) / statistics.mean(values)


def completion(base_url, prompt, max_output_tokens, timeout_s, *, opener=None, temperature=0):
    """Read SSE token events; never infer TTFT from a non-streamed response."""
    parsed = urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username is not None
            or parsed.password is not None or parsed.port is None or parsed.query or parsed.fragment
            or parsed.path.rstrip("/") != "/v1"):
        raise ValueError("Only the owned loopback server may receive workload requests")
    if temperature not in (0, 1):
        raise ValueError("Only frozen greedy evaluation or sampled serving smoke is supported")
    payload = {"model": "servetune-glimmer", "messages": [{"role": "user", "content": prompt}],
               "temperature": temperature, "max_tokens": max_output_tokens, "stream": True,
               "stream_options": {"include_usage": True},
               "chat_template_kwargs": {"reasoning_strength": "low"}}
    if not base_url.rstrip("/").endswith("/v1"):
        raise ValueError("Local inference base URL must include /v1 exactly once")
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    first = None
    parts, reasoning = [], []
    usage, finish, done = None, None, False
    consumed = 0
    with opener.open(request, timeout=timeout_s) as response:
        for raw in response:
            if time.monotonic() - started > timeout_s:
                raise TimeoutError("Total request deadline exceeded")
            consumed += len(raw)
            if consumed > 8_000_000:
                raise ValueError("Streaming response exceeded evidence size bound")
            if not raw.startswith(b"data:"):
                continue
            line = raw[5:].strip()
            if line == b"[DONE]":
                done = True
                break
            event = json.loads(line)
            if event.get("usage") is not None:
                usage = event["usage"]
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                content = delta.get("content") or ""
                thought = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if content or thought:
                    if first is None:
                        first = time.monotonic()
                    parts.append(content)
                    reasoning.append(thought)
                if choice.get("finish_reason") is not None:
                    finish = choice["finish_reason"]
    if not done or first is None or finish not in ("stop", "length") or not isinstance(usage, dict):
        raise ValueError("Incomplete stream, missing token timing, or missing engine usage")
    for name in ("prompt_tokens", "completion_tokens"):
        if type(usage.get(name)) is not int or usage[name] <= 0:
            raise ValueError("Engine usage must contain positive actual token counts")
    return {"text": "".join(parts), "reasoning_text": "".join(reasoning),
            "finish_reason": finish, "usage": usage,
            "ttft_from_dispatch_s": first - started, "elapsed_from_dispatch_s": time.monotonic() - started}


def run_trace(trace, request_fn, meter, *, clock=time.monotonic, sleeper=time.sleep):
    rows = trace["requests"]
    if not rows or rows[0]["arrival_s"] != 0 or len(rows) > 256:
        raise ValueError("Trace must start at zero and contain 1–256 requests")
    offsets = [row["arrival_s"] for row in rows]
    if any(not math.isfinite(x) or x < 0 for x in offsets) or offsets != sorted(offsets):
        raise ValueError("Arrival offsets must be finite, nonnegative and sorted")
    # Allocate all workers before the energy window. No client semaphore changes offered load.
    with ThreadPoolExecutor(max_workers=len(rows)) as pool:
        meter.start()
        start = clock()

        def serve(row):
            scheduled = start + row["arrival_s"]
            sleeper(max(0.0, scheduled - clock()))
            dispatched = clock()
            try:
                result = request_fn(row)
                result.update({"id": row["id"], "scheduled_s": row["arrival_s"],
                               "dispatch_lag_s": max(0.0, dispatched - scheduled),
                               "end_to_end_s": clock() - scheduled,
                               "ttft_s": dispatched - scheduled + result["ttft_from_dispatch_s"], "error": None})
                return result
            except Exception as exc:
                # Exception messages and HTTP bodies may carry untrusted content; retain the class only.
                return {"id": row["id"], "scheduled_s": row["arrival_s"],
                        "dispatch_lag_s": max(0.0, dispatched - scheduled),
                        "end_to_end_s": clock() - scheduled, "error": type(exc).__name__}

        futures = [pool.submit(serve, row) for row in rows]
        try:
            outcomes = [future.result() for future in futures]
        finally:
            energy = meter.stop()
        duration = clock() - start
    good = [row for row in outcomes if row["error"] is None]
    output_tokens = sum(row["usage"]["completion_tokens"] for row in good)
    prompt_tokens = sum(row["usage"]["prompt_tokens"] for row in good)
    complete = len(good) == len(rows)
    joules = energy["joules"]
    if not math.isfinite(joules) or joules <= 0:
        raise ValueError("Invalid complete-workload energy measurement")
    return {"trace_sha256": digest(trace), "measurement_window": "first scheduled arrival through final completion",
            "energy_label": "GPU energy (NVML)", "requests": outcomes, "energy": energy,
            "status": "pass" if complete else "fail", "all_requests_completed": complete,
            "completed_requests": len(good), "scheduled_requests": len(rows),
            "prompt_tokens": prompt_tokens, "generated_tokens": output_tokens,
            "joules": joules, "joules_per_output_token": joules / output_tokens if output_tokens else None,
            "joules_per_completed_request": joules / len(good) if good else None,
            "output_tokens_per_second": output_tokens / duration if duration > 0 else None,
            "duration_s": duration,
            "p50_latency_s": percentile([r["end_to_end_s"] for r in good], 0.5),
            "p95_latency_s": percentile([r["end_to_end_s"] for r in good], 0.95),
            "p50_ttft_s": percentile([r["ttft_s"] for r in good], 0.5),
            "p95_ttft_s": percentile([r["ttft_s"] for r in good], 0.95)}


def length_drift(candidate, reference):
    before, after = reference["generated_tokens"], candidate["generated_tokens"]
    if before <= 0 or after <= 0:
        raise ValueError("Cannot compare length drift without generated tokens")
    fraction = abs(after - before) / before
    both_improve = (candidate["joules_per_output_token"] < reference["joules_per_output_token"]
                    and candidate["joules_per_completed_request"] < reference["joules_per_completed_request"])
    return {"fraction": fraction, "flagged": fraction > 0.02,
            "eligible": fraction <= 0.02 or both_improve}
