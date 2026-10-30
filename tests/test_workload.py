from copy import deepcopy
from io import BytesIO
import json
import unittest

from servetune.config import DEFAULT
from servetune.workload import completion, coefficient_of_variation, length_drift, make_trace, run_trace


class Response(BytesIO):
    pass


class Opener:
    def __init__(self, events):
        self.raw = b"".join(b"data: " + (e if isinstance(e, bytes) else json.dumps(e).encode()) + b"\n\n" for e in events)

    def open(self, request, timeout):
        self.request = request
        return Response(self.raw)


class Meter:
    def start(self):
        self.started = True

    def stop(self):
        return {"joules": 20.0, "duration_s": 0.1}


class WorkloadTests(unittest.TestCase):
    def test_stream_url_and_actual_usage(self):
        opener = Opener([{"choices": [{"delta": {"role": "assistant"}}]},
                         {"choices": [{"delta": {"content": "ready"}, "finish_reason": "stop"}]},
                         {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 1}}, b"[DONE]"])
        result = completion("http://127.0.0.1:8000/v1", "test", 32, 1, opener=opener)
        self.assertEqual(opener.request.full_url, "http://127.0.0.1:8000/v1/chat/completions")
        self.assertEqual(result["usage"]["completion_tokens"], 1)
        self.assertEqual(result["text"], "ready")
        self.assertIsNotNone(result["ttft_from_dispatch_s"])

    def test_loopback_impersonation_rejected_before_transport(self):
        for url in ("http://127.0.0.1:8000@evil.test/v1", "https://127.0.0.1:8000/v1",
                    "http://127.0.0.1:8000/v1?x=1", "http://127.0.0.1:8000/v1/v1"):
            with self.assertRaises(ValueError):
                completion(url, "test", 32, 1)

    def test_missing_usage_or_done_is_not_a_success(self):
        for events in ([{"choices": [{"delta": {"content": "ready"}, "finish_reason": "stop"}]}, b"[DONE]"],
                       [{"choices": [{"delta": {"content": "ready"}, "finish_reason": "stop"}]},
                        {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}]):
            with self.assertRaises(ValueError):
                completion("http://127.0.0.1:8000/v1", "test", 32, 1, opener=Opener(events))

    def test_trace_is_frozen_and_never_silently_truncates(self):
        settings = deepcopy(DEFAULT["trace"])
        a, b = make_trace(["a", "b"], settings), make_trace(["a", "b"], settings)
        self.assertEqual(a, b)
        self.assertEqual(a["requests"][0]["arrival_s"], 0)
        settings["max_requests"] = 1
        with self.assertRaises(ValueError):
            make_trace(["a"], settings)

    def test_partial_failure_cannot_pass_full_workload(self):
        trace = {"requests": [{"id": "a", "arrival_s": 0}, {"id": "b", "arrival_s": 0}]}
        def request(row):
            if row["id"] == "b":
                raise TimeoutError("simulated")
            return {"text": "ok", "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                    "ttft_from_dispatch_s": 0.0}
        result = run_trace(trace, request, Meter())
        self.assertFalse(result["all_requests_completed"])
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["generated_tokens"], 2)
        self.assertEqual(result["joules_per_output_token"], 10)
        self.assertEqual(result["completed_requests"], 1)

    def test_length_drift_requires_both_energy_metrics(self):
        before = {"generated_tokens": 100, "joules_per_output_token": 2, "joules_per_completed_request": 10}
        after = {"generated_tokens": 120, "joules_per_output_token": 1.9, "joules_per_completed_request": 11}
        self.assertTrue(length_drift(after, before)["flagged"])
        self.assertFalse(length_drift(after, before)["eligible"])
        after["joules_per_completed_request"] = 9
        self.assertTrue(length_drift(after, before)["eligible"])

    def test_cv_rejects_incomplete_or_nonfinite_evidence(self):
        for values in ([1, 1], [1, 1, float("nan")], [0, 0, 0]):
            with self.assertRaises(ValueError):
                coefficient_of_variation(values)


if __name__ == "__main__":
    unittest.main()
