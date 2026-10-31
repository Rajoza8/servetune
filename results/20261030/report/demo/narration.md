# ServeTune narration

**VERIFIED FINAL CONFIRMATION**

Duration: 180 seconds. Six chapters use the v4 20/25/35/25/50/25 timing ratio.

## 00:00:00,000 — The problem

ServeTune measures serving configurations for an open-weight Meta model. This record contains 111 indexed trials, including 111 verified live observations. The goal is lower GPU energy per token under a fixed incoming workload, a latency target and a quality gate. The final comparison uses fresh confirmation measurements.

## 00:00:20,000 — The measured loop

The trace fixes when requests arrive, including queueing in latency. Each bounded configuration starts a fresh engine, warms up, and measures the complete workload through the final response. NVML cumulative counters measure GPU energy. Actual tokens and completed requests are counted. Quality, latency, failures and length drift govern whether a change can be kept.

## 00:00:45,000 — The energy map

The record contains 36 energy-map trials across the recorded load levels. The plot pairs joules per output token with ninety-fifth percentile latency. Lower values are preferable. The frontier uses eligible observations; failures remain in the record. Energy per completed request is reported alongside energy per token. These measurements apply only to the recorded GPU, engine, model revision and workload.

## 00:01:20,000 — BF16 and FP8

Fresh eligible confirmation records show a median of 0.4685 GPU joules per output token for BF16 defaults, and 0.4663 for FP8 defaults. These are observed values, with no assumed positive saving. The quality comparison must be read alongside them, using the predeclared two-percentage-point tolerance on held-out items.

## 00:01:45,000 — Spark and random search

The arm histories retain 17 proposal and decision records. Random search and Muse Spark receive the same configuration space and allocated time budget. Spark's planning wait, engine loads, warmup, evaluations, failures and incomplete trials count against its clock. Each arm sees only its own search history. The timeline shows the actual hypothesis and the recorded accept or revert decision. Tuning observations are process evidence, not headline results. Both arms selected the same confirmed configuration; those aliases share one set of measurements, not independent confirmations.

## 00:02:35,000 — Results and limits

The final table contains 10 live confirmation attempts, with 2 eligible configuration groups. Failed or ineligible confirmations stay in the report. Quality wording is within the predeclared two-percentage-point tolerance on this evaluation. The repository includes frozen inputs, raw evidence, offline reports and rebuild instructions. No whole-system energy, general speedup or state-of-the-art claim is made.
