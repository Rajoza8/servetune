# ServeDoctor

**An on-call agent for LLM serving, and ServeIncidents, a benchmark of real GPU incidents with sealed answers.**

A local Muse Glimmer model watches a live vLLM server every 30 seconds. On an anomaly it escalates to Muse Spark or
Muse Wonder, which names the root cause and proposes at most two fixes from a fixed whitelist. In live runs the fix is
applied, recovery is measured on real requests, and the change is rolled back if the service has not recovered.

Built during the Meta AI Developer Hackathon (Push the Frontier), October 29 – November 3, 2026. See the dated
[build record](BUILT_DURING_HACKATHON.md).

**Results page with live-repair replays:** https://rajoza8.github.io/servetune/ (built from the committed results by
`scripts/build_site.py`; it makes no API calls).

## Results at a glance

| | Result |
| --- | --- |
| **Hard set, correct diagnoses** (12 faulty incidents) | Glimmer alone (local, free) **11**, Muse Spark **11**, Muse Wonder 10, Glimmer→Wonder 9, Glimmer→Spark 8, threshold rules 7 |
| **Hard set, harmful actions** | **0** for every AI agent; threshold rules **5**, each one stopping a harmless GPU job (all 5 decoy cases) |
| **Two-cause incidents fully fixed** | **0 of 4** for every agent: each fixed only the loudest cause |
| **v0 test set** (13 faults, 3 healthy) | Glimmer, Spark and Wonder 13/13; rules, Glimmer→Spark and Glimmer→Wonder 11/13; no harmful actions |
| **Live repairs on the GPU** | The agent (Glimmer→Spark) recovered **5 of 6** injected faults in 84–203 s from fault start; its one failed fix was rolled back automatically. The rules baseline also recovered 5 of 6, failing a different incident. |
| **Cost** | Hard set: Spark $0.54, Wonder $1.64, Glimmer→Spark $0.08, Glimmer $0. |

Scores are an agent's first incident decision on recorded incidents, replayed identically to every agent. Samples are
small (13 and 12 faulty incidents), so a one-incident difference is noise; the robust findings are the zero harmful
actions by every model agent against five by the rules, and the universal failure on two-cause incidents.

Full packages, with every decision, answer key, recording and hash:
[v0](results/servedoctor-20261102/README.md) · [Hard set (15 of 16 frozen incidents)](results/servedoctor-hard-20261103/README.md).

## How Meta's models are used

| Model | Access | Role |
| --- | --- | --- |
| **Muse Glimmer 30B** (open weights, BF16, pinned revision) | Served locally with vLLM on one RTX PRO 6000 Blackwell | The model being served; the always-on monitor; a diagnosing agent on its own |
| **Muse Spark 1.3** | Meta Model API | The expert that diagnoses escalated anomalies |
| **Muse Wonder 1.0** | Meta Model API | An alternative, stronger expert, compared with Spark |

## How it works

```
 every 30 s                        on an anomaly                   one action round
┌────────────┐   telemetry   ┌─────────────────┐  diagnosis  ┌──────────────────────────┐
│  Glimmer   │ ────────────▶ │ Spark or Wonder │ ──────────▶ │ whitelisted fix          │
│ (monitor)  │  "anomaly?"   │    (expert)     │  + ≤2 fixes │ → verify → or roll back  │
└────────────┘               └─────────────────┘             └──────────────────────────┘
```

- **Observation:** at each checkpoint every agent gets the same snapshot an operator would see, built only from data up
  to that moment: the SLO, current and normal config, the change log, three minutes of metrics in 10-second steps (traffic,
  latency, errors, queue, KV-cache use, preemptions, throughput, GPU power and utilization), the GPU process table and recent
  engine log lines.
- **Actions:** one engine setting change (the engine restarts), a gateway rate limit or prompt-length cap, stopping a GPU job
  this run launched, a consolidation recommendation, escalation, or nothing. Anything else is rejected before it runs.
- **Verification:** requests that arrive 30–90 seconds after the fix must meet the SLO (p95 ≤ 10 s, errors ≤ 1%); otherwise
  the change is undone and a human is paged.

## The benchmark: ServeIncidents

Each incident is six minutes of real traffic (GSM8K questions, open-loop arrivals at half of measured capacity) against
vLLM serving Glimmer, with injected faults, recorded once per second: vLLM metrics, NVML GPU state and process table,
client outcomes, gateway policy, change log and engine log lines. True causes, onsets and allowed fixes live in sealed answer
keys that no agent sees, and incident IDs are shuffled.

- **v0:** 24 incidents (8 development, 16 held-out test): traffic surge, long-prompt flood, KV-cache starvation, batch limit
  too low, context limit too small, GPU contention, underused GPU and healthy controls. Tuning was allowed only on development
  incidents; everything was frozen before test recording.
- **Hard:** built because v0 saturated. Harmless config changes on every deploy, decoy GPU jobs sharing names with real
  culprits, four two-cause incidents, faults just over the SLO line and red-herring alerts, with nothing tuned on it.
  `hard-16` could not start because of a generator defect and was excluded, with the reason recorded, before any
  validation or scoring. A symptom check declared in advance found one more incident with no SLO breach; both scoreboards are
  published. Design: [docs/SERVEDOCTOR_HARD.md](docs/SERVEDOCTOR_HARD.md).

Prior work (searched October 31, 2026): agent benchmarks such as SREGym, AIOpsLab and ITBench target microservices; *Beyond
Microservices* (ICPE 2026) injects faults into LLM serving but evaluates classical root-cause methods without remediation.
To our knowledge no public benchmark evaluates LLM agents that diagnose and fix serving-engine incidents with recovery verified
live.

## Check the results yourself (no GPU, no API key)

```sh
git clone https://github.com/Rajoza8/servetune && cd servetune
python3 -m unittest discover -s tests -q
python3 -m servedoctor score --study-dir results/servedoctor-20261102 --split test
python3 -m servedoctor score --study-dir results/servedoctor-hard-20261103/analysis --split hard
python3 -m servedoctor score --study-dir results/servedoctor-hard-20261103/analysis --split hard --valid-only
python3 scripts/build_site.py
```

Rehearse the whole pipeline on synthetic incidents (labelled synthetic, never a result):

```sh
python3 -m servedoctor simulate --hard --capacity-rps 8 --out runs/sd-hard-sim
python3 -m servedoctor evaluate --study-dir runs/sd-hard-sim --arms rules --split hard
python3 -m servedoctor report --study-dir runs/sd-hard-sim
```

Recording new incidents needs an NVIDIA GPU, a Glimmer-capable vLLM and the pinned model revision; see
[docs/SERVEDOCTOR_GPU_BRIEF.md](docs/SERVEDOCTOR_GPU_BRIEF.md).

## Limits

- One GPU type, one engine (vLLM) and one served model. v0 and the Hard set ran on different hosts (8 vs 6 requests/s
  capacity), so cross-study numbers are not like-for-like.
- Hard-set scores replay recorded incidents; the live evidence is the 12 v0 repair runs. Gateway fixes for surges and long
  prompts recovered latency by shedding a large share of requests; shed rates are reported separately.
- Wonder's six invalid answers hit the fixed 2,048-token output cap while still reasoning.

## Repository map

| Path | What it is |
| --- | --- |
| `servedoctor/` | The agent, recorder, fault injectors, evaluation, scoring, live loop and Hard-set generator |
| `servetune/` | Engine lifecycle, NVML energy and workload code reused by ServeDoctor, plus the earlier ServeTune study |
| `configs/` | Frozen study configurations (`servedoctor.json`, `servedoctor-hard.json`) |
| `results/servedoctor-20261102/` | v0: recordings, decisions, answer keys, live runs, provenance |
| `results/servedoctor-hard-20261103/` | Hard set: the 15-incident analysis and the preserved original frozen attempt |
| `results/20261030/` | ServeTune v4 energy study |
| `docs/` | Design docs and the results page (`index.html`) |
| `tests/` | Offline tests, including a fake vLLM server |

## Earlier in the hackathon: ServeTune

ServeTune tuned vLLM settings for energy per token under a frozen workload. Across 111 live trials neither the Spark-guided
policy nor random search found an accepted saving; FP8 used 0.47% less GPU energy per token than BF16 and cut p95 latency
by 49.5%. Details: [SERVETUNE.md](SERVETUNE.md) and [results/20261030](results/20261030/README.md).

## License

MIT. Model weights, datasets and third-party tools keep their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
