# ServeDoctor and ServeIncidents

**ServeDoctor** is an on-call agent for LLM serving. A local Muse Glimmer model
watches a live vLLM deployment every 30 seconds. When it sees an anomaly it
escalates to Muse Spark, which names the root cause and proposes at most two
fixes from a fixed list of allowed actions. In live runs the fix is applied,
recovery is measured on real requests, and the change is rolled back if the
service does not recover.

**ServeIncidents** is the benchmark used to evaluate it: serving incidents
recorded on a real GPU, each with a sealed answer key.

Status: the code is complete and tested offline. **No ServeIncidents result
exists until the GPU recordings are made.** Synthetic rehearsal output is
labelled as such and must never be reported as a result.

## What an incident is

Each incident is a directory recorded on one RTX PRO 6000 Blackwell serving
Muse Glimmer with vLLM:

| File | Content |
| --- | --- |
| `telemetry.jsonl` | One row per second: vLLM Prometheus metrics (running, waiting, KV-cache use, preemptions, token counters, latency histograms), NVML (power, utilization, memory, clocks, GPU process table), client-side arrivals, completions, errors by HTTP status, latencies, gateway policy, filtered engine log lines |
| `requests.jsonl` | Every request: class, estimated prompt tokens, status, latency from scheduled arrival, TTFT, tokens |
| `events.json` | The change log an operator would see. Every incident has a deploy event at t=0 and an unrelated note, so a change is never a giveaway |
| `engine_config.json`, `slo.json` | The deployed knobs and the service-level objective |
| `manifest.json` | SHA-256 of every file |

Answer keys live in `answers/`, which no agent reads. Incident IDs are
shuffled, so an ID reveals nothing.

## Fault types

All are injected without root access.

| Root cause | How it is injected | Valid fix | Harmful examples |
| --- | --- | --- | --- |
| `traffic_surge` | Arrival rate jumps to 1.3–2.2× measured capacity | Gateway rate limit | Lowering engine limits |
| `long_prompt_flood` | 30–80% of requests become 2.3k–3.5k-token prompts | Gateway prompt-length cap or rate limit | Lowering KV memory or sequence limit |
| `kv_cache_starvation` | Deploy lowers `gpu_memory_utilization` | Raise it | Lower it further, or raise the sequence limit |
| `batch_limit_too_low` | Deploy lowers `max_num_seqs` to 2–8 | Raise it | Lower it, or shed load |
| `context_limit_too_small` | Deploy lowers `max_model_len` below the medium prompts | Raise it | Lower it |
| `gpu_contention` | A neighbouring "embedding batch" job runs matmuls on the same GPU | Stop that process | Lower KV memory |
| `underutilization` | Traffic at 8–12% of capacity while the GPU draws high power (ServeTune's 470 W finding) | Recommend consolidation (advisory) | Any change |
| `healthy` (controls) | Normal load with a brief harmless spike | No action | Any change |

Version 0 has 6 fault types × 3 severities, 2 underutilization and 4 healthy
controls: 24 incidents. 8 are for development (one per type, plus one control
and one underutilization incident); 16 are held out for testing. A healthy
reference recording supplies every arm with the same "normal profile".

## Arms

Every arm sees the same observation at each 30-second checkpoint, built only
from data at or before that moment (no look-ahead). An arm's first incident
decision is final, as it would be on call.

| Arm | What decides |
| --- | --- |
| `rules` | Transparent thresholds written by the fault designers: an optimistic baseline, not a strawman |
| `glimmer` | Muse Glimmer (local, open weights) diagnoses at every checkpoint |
| `spark` | Muse Spark (Meta API) diagnoses at every checkpoint |
| `glimmer_to_spark` | Glimmer monitors; only anomalies are escalated to Spark |

## Scoring

- **Detection:** flagged at or after onset. A flag on a healthy control, or
  before a workload fault starts, is a false alarm.
- **Diagnosis:** the first flagged root cause equals the truth.
- **Fix proposed:** at least one action matches the cause's fix rule (including
  the direction of a knob change), and no action is harmful.
- **Harmful:** any action matches a harmful rule; stopping any process other
  than the injected job is always harmful.
- **Cost:** Spark calls and dollars per arm, from reported token usage.
- **Live runs (subset):** recovered (p95 latency and error rate back within the
  SLO on requests 30–90 s after the fix), time to recover, shed rate, restart
  time, rollbacks.

## Safety boundaries

- Agents never run shell commands. Actions are validated against a whitelist
  with hard bounds before anything executes.
- Engine changes restart only the vLLM process group this harness started.
- `stop_gpu_process` succeeds only for the batch job this run launched,
  verified by a random environment marker.
- Paid calls reserve their worst-case cost in a separate ServeDoctor ledger
  (Meta $50, Baseten $20) before dispatch. Failed calls keep the reservation.

## Commands

```sh
python3 -m servedoctor simulate --out runs/sd-sim          # synthetic rehearsal only
python3 -m servedoctor evaluate --study-dir runs/sd-sim --arms rules
python3 -m servedoctor report --study-dir runs/sd-sim
```

The GPU procedure is in [SERVEDOCTOR_GPU_BRIEF.md](SERVEDOCTOR_GPU_BRIEF.md).

## Prior work and the claim

Searched on October 31, 2026. Closest: *Beyond Microservices: Testing Web-Scale
RCA Methods on GPU-Driven LLM Workloads* (ICPE 2026 companion; code at
github.com/exalsius/rca-llm) injects CPU/memory/GPU stress and network faults
into LLM serving on Kubernetes and evaluates 24 classical root-cause methods,
with no LLM agents and no remediation. SREGym, AIOpsLab, ITBench and similar
benchmarks evaluate SRE agents on microservices; SREGym's problem list has no
LLM-serving, GPU or KV-cache scenarios. SRE-World (NeurIPS 2026) was checked
only at abstract level.

The claim we make: to our knowledge, no public benchmark evaluates LLM agents
that diagnose **and** fix **serving-engine** incidents in LLM inference with
recovery verified live against a latency target. We do not claim the agent
beats the rule baseline unless the results show it, and we do not claim
generality beyond one GPU, one engine and one model.
