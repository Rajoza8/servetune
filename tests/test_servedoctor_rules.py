import unittest

from servedoctor.rules import decide


def observation(arrivals, *, sequence_limit, running, waiting, latency):
    rows = [{"arrivals_rps": rate, "shed_rps": 0, "errors": {}, "p95_latency_s": p95,
             "waiting_max": queue, "kv_usage_pct_max": 0.4, "preemptions_per_s": 0,
             "prompt_tokens_mean": 150, "gen_tokens_per_s": 100, "running": active}
            for rate, active, queue, p95 in zip(arrivals, running, waiting, latency)]
    return {"recent_10s_buckets": rows, "engine_config": {"max_num_seqs": sequence_limit},
            "reference_engine_config": {"max_num_seqs": 64}, "gpu_processes": [],
            "normal_profile": {"arrivals_rps": 2.9, "prompt_tokens_mean": 205,
                               "gen_tokens_per_s": 365.3}, "slo": {"p95_latency_s": 10}}


class RuleRegressionTests(unittest.TestCase):
    def test_noisy_ordinary_arrivals_preserve_saturated_batch_limit_diagnosis(self):
        # Dev inc-03 at 30 s: a 3.833 rps burst accompanies a deploy from 64 to 4 sequences.
        result = decide(observation([3.6, 4.6, 3.3], sequence_limit=4,
                                    running=[3.4, 4, 4], waiting=[28, 66, 89], latency=[4.99, 12.37, 24.7]))
        self.assertEqual(result["root_cause"], "batch_limit_too_low")
        self.assertEqual(result["actions"], [{"type": "set_engine_config", "knob": "max_num_seqs", "value": 64}])

    def test_genuine_surge_with_unchanged_sequence_limit_still_sheds_load(self):
        result = decide(observation([10.2, 10.2, 10.2], sequence_limit=64,
                                    running=[56, 64, 64], waiting=[30, 80, 120], latency=[12, 15, 20]))
        self.assertEqual(result["root_cause"], "traffic_surge")
        self.assertEqual(result["actions"], [{"type": "gateway_rate_limit", "max_rps": 4.64}])


if __name__ == "__main__":
    unittest.main()
