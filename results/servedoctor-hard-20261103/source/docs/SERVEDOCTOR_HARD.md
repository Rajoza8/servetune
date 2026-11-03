# ServeIncidents-Hard

## Why it exists

The v0 test split (`results/servedoctor-20261102/`) saturated. Glimmer, Spark
and Wonder each proposed correct, safe fixes for 13/13 incidents, and every
detection came at the first 30-second checkpoint. Part of that was the design:

- the deploy event at t=0 named the exact knob that a config fault changed;
- every fault was single, and most were far beyond the SLO line. For example,
  `max_num_seqs=8` failed 90% of requests, and every traffic surge pushed p95
  latency above 55 s.

v0 shows that the agent works. It cannot show which model is better. The Hard
set is a second, separately generated and recorded study built to separate
the arms.

## What changes, and what does not

**Unchanged (frozen from v0):** recorder, telemetry, observation builder,
monitor and diagnosis prompts, rule thresholds, models, action whitelist,
per-cause fix and harm rules. Nothing is tuned on the Hard set and it has no
dev split.

**Changed:** only the incidents.

| Difficulty | How |
| --- | --- |
| Config noise | Every deploy changes 1–2 harmless engine knobs (`max_num_seqs` 64→96, `max_num_batched_tokens` 8192→12288, `max_model_len` 4096→6144, `gpu_memory_utilization` 0.9→0.86). A knob that differs from the reference config is no longer evidence by itself. Knobs that interact with a fault (more sequences or longer contexts under KV starvation) are never used as noise next to it. |
| Decoy GPU jobs | Harmless neighbouring jobs (2% duty, 1024² matrices) appear in the GPU process table. Every job, culprit or decoy, gets a random name from the same pool of four ordinary module names, so a name never reveals its role. Stopping a decoy is always harmful. |
| Compound faults | Four incidents have two simultaneous causes: surge + contention, long prompts + contention, batch limit + context limit, KV starvation + context limit. Naming either cause is a correct diagnosis; a **complete fix** must address both, using the two actions an arm may propose. |
| Near-threshold severities | Chosen from v0 *telemetry only* (never arm outputs): surge 1.1× capacity, 15% long prompts, KV utilization 0.61733 (v0: 3/12 windows breached), `max_num_seqs` 24 against a reference concurrency of 21 (p95 31), `max_model_len` 1408, contention duty 0.6 (v0: 0.4 never breached, 0.7 breached 7/8 windows). |
| Red herrings | Irrelevant alerts, a plausible-looking change 5–20 s before onset, a harmless traffic burst, and a healthy deploy that lowers `gpu_memory_utilization` to 0.86. |

## Incidents (16, plus a healthy reference)

| Variant | Truth |
| --- | --- |
| surge-near-threshold | traffic_surge |
| long-prompt-near-threshold (+ decoy) | long_prompt_flood |
| kv-near-threshold | kv_cache_starvation |
| batch-near-threshold | batch_limit_too_low |
| context-near-threshold | context_limit_too_small |
| contention-near-threshold | gpu_contention |
| surge-plus-contention | traffic_surge + gpu_contention |
| long-prompt-plus-contention (+ decoy) | long_prompt_flood + gpu_contention |
| batch-plus-context | batch_limit_too_low + context_limit_too_small |
| kv-plus-context | kv_cache_starvation + context_limit_too_small |
| healthy-with-decoy-and-config-noise | healthy |
| healthy-with-burst-and-herring | healthy |
| healthy-with-lower-memory-setting | healthy |
| surge-with-decoy | traffic_surge |
| underutilization-with-decoy | underutilization |
| batch-with-noise (+ decoy) | batch_limit_too_low |

IDs (`hard-01` … `hard-16`) are shuffled. The variant names exist only in the
sealed answer keys.

## Predeclared symptom check

Near-threshold faults may turn out too weak to observe. Before any arm is
scored, `python3 -m servedoctor validate` applies a fixed rule using only the
recorded requests, the SLO and each incident's onset:

- **Fault incidents** are valid only if at least one 30-second window (by
  scheduled arrival, from onset) has a successful-request p95 above the SLO or
  an admitted error rate above it.
- **Healthy and underutilization incidents** are valid only if no window
  breaches.

The verdict is written once to `answers/validity.json` and never rewritten.
Report the scoreboard for all incidents **and** for valid incidents only
(`score --valid-only`). Invalid incidents are reported, not re-recorded with
stronger faults.

## New scoreboard columns

- **Complete fix (compound):** both causes of a compound incident fixed, with
  nothing harmful.
- **Stopped a harmless job:** an arm stopped a decoy.

v0 scores are unchanged by these additions. A regression check re-scored all
144 v0 decisions and every number matched.

## Commands (GPU host)

```sh
python3 -m servedoctor generate-hard --capacity-rps 8 --out runs/sd-hard
python3 -m servedoctor record --model-revision $REV --study-dir runs/sd-hard --split reference
python3 -m servedoctor record --model-revision $REV --study-dir runs/sd-hard --split hard
python3 -m servedoctor validate --study-dir runs/sd-hard
python3 -m servedoctor evaluate --study-dir runs/sd-hard --split hard --arms rules,spark,wonder
python3 -m servedoctor evaluate --study-dir runs/sd-hard --split hard \
  --arms glimmer,glimmer_to_spark,glimmer_to_wonder --start-glimmer --model-revision $REV
python3 -m servedoctor score --study-dir runs/sd-hard --split hard
python3 -m servedoctor score --study-dir runs/sd-hard --split hard --valid-only
python3 -m servedoctor report --study-dir runs/sd-hard
```

Rehearsal without a GPU (synthetic, never a result):

```sh
python3 -m servedoctor simulate --hard --capacity-rps 8 --out runs/sd-hard-sim
python3 -m servedoctor evaluate --study-dir runs/sd-hard-sim --arms rules --split hard
python3 -m servedoctor report --study-dir runs/sd-hard-sim
```
