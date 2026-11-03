# ServeDoctor: GPU incident study

On the 16 held-out test incidents (13 faulty, 3 healthy), Glimmer, Spark and
Wonder each proposed 13/13 correct, safe fixes. Glimmer→Spark, Glimmer→Wonder
and threshold rules each proposed 11/13. All arms made zero harmful proposals.
These are first-decision scores on recorded incidents, not live repairs.

On six separately selected live incidents per arm, Glimmer→Spark and rules each
met the canonical latency/error recovery criterion in **5/6** runs. That
criterion excludes shedding. The full configured post-action target, including
a 5% shed cap, was met in **4/6** cascade runs and **3/6** rules runs. Separate
temporal runs and six cases do not establish causal or general superiority.

## Reproduce the scores

From the repository root; no GPU, API key or provider calls are required:

```sh
python3 -m servedoctor score --study-dir results/servedoctor-20261102 --split dev
python3 -m servedoctor score --study-dir results/servedoctor-20261102 --split test
python3 scripts/build_site.py
```

[report.html](report.html) and [report.json](report.json) contain the recorded
arm results. The [live-window audit](provenance/operations/live-window-audit.json)
contains exact cohort bounds, counts, actions, restart timing and source hashes
for all 12 live runs. See [the benchmark methods](../../docs/SERVEDOCTOR.md) and
[GPU setup guide](../../docs/RUNNING_ON_GPU.md) for new experiments.

## Hardware, models and commitments

The final recordings used one RTX PRO 6000 Blackwell Workstation Edition,
96 GB advertised / 97,887 MiB NVML memory, compute capability 12.0, GPU UUID
`GPU-549b0b27-6ca2-2fca-e5aa-a0f67a43b81b`, driver `580.159.03`, Python
`3.12.3`, PyTorch `2.13.0+cu130` and vLLM
`0.26.1rc1.dev608+g99a10304d`. Container image:
`vastai/vllm@sha256:d17aa376347c086ce53d9f9ac3a70e904acbc37882a7ee0b1ba4f7f538f8d843`.
BF16 `meta-models/Muse-Glimmer-30B` model and tokenizer both use revision
`cec94fcfd6512f2cfe708138c32533b346ea4f69`, resolved from the offline cache.
These driver and host identities differ from the earlier ServeTune study.

| Item | Frozen value |
| --- | --- |
| Experiment source | `a0b4deb6e9545b9d21fde472ad4686645b083bc6` |
| Experiment freeze time | `2026-11-02T02:15:20.469452+00:00` |
| Freeze SHA256 | `7428210756fe9d61599d13f2182416b916f1a43627d178030f73f071b6845319` |
| Generation time | `2026-11-01T22:52:54.909387Z` |
| Generation source | `3fea48a84cec07231f3a658f57ccc7b125eda8ae` |
| Answer commitment | `89af5cbf353c4427b3bacb6b80cef2cacb9b7361db00b21f11a32efeeea7a79a` |
| Scenario commitment | `51ef576470c93bb68f7fc2a1d22569356ed8b80f113904a031bcc68501e52ca2` |
| Descriptive live-window plan SHA256 | `68d027631715fc7862bc8e2299c8ebfd50d0515ce62bf8536b96cae6a1749fee` |
| Live-window audit SHA256 | `15f9ed3ad4c55316112a04608eb27d28ae25d17081708e1676c7cd8c81a8757d` |

The [commit map](../COMMIT_MAP.md) relates historical source IDs to the
metadata-normalized commits. Publication commits are distinct from experiment
sources; the experiment freeze was not restamped after test recording.

The original recording host became unavailable. Its measurements remain
separate historical evidence; the final study was rerun on the replacement
GPU above. The final study has one healthy reference, 8 development incidents
(7 faulty, 1 healthy) and 16 test incidents (13 faulty, 3 healthy). Observations
use only telemetry available at each checkpoint, and an arm's first incident
decision is final.

The reference and eight development recordings originated in `sd-study-r2`.
After a Wonder HTTP404 halted evaluation, `sd-study-r2-api2` inherited those nine
sealed recordings, nine runtime-answer files and 24 completed rules/Spark/Glimmer
decisions by verified binary copy, retaining the cumulative ledger. The failed
Wonder partial remains separate. Test and live recordings originated in API2,
with the explicit incident-23 collection repair described below. No prompts,
models, prices, rules, scoring or incident specifications changed during that
copy; the source change added explicit Meta transport selection.

Test recording was frozen as two batches of eight IDs, adding an engine startup
without changing arrivals, durations or measurement policy. The API2 batch-plan
SHA256 is `6ed28c97bd2a330329c091c660c924d0d823ca5176cfc210804986e4b876d6f3`.
Both escalation arms scored 6/7 correct safe fixes, zero harm and false alarms,
and six API calls on development. Spark cost $0.0363 versus Wonder $0.1509.
The predeclared selection policy prioritized fixes, harm, diagnosis, false
alarms, detection and cost, with Spark as final tie-breaker. It selected
Glimmer→Spark and the following live cases before test recording:

| Cause | Test ID |
| --- | --- |
| KV-cache starvation | `inc-02` |
| Context limit too small | `inc-04` |
| Batch limit too low | `inc-05` |
| Traffic surge | `inc-06` |
| GPU contention | `inc-09` |
| Long-prompt flood | `inc-15` |

## Capacity and development calibration

Replacement calibration ran 60-second steps at 2, 4, 6, 8 and 10 requests/s and stopped at the first SLO violation. Successful-request p95 latency was 5.44, 6.77, 6.32, 9.02 and 18.48 seconds respectively, with no failed requests. Measured capacity is 8 requests/s under the 10-second latency SLO and 1% error cap. The completed 10 requests/s step exceeded the latency SLO. The replacement base engine at `gpu_memory_utilization=0.9` reported 27.38 GiB KV memory and 550,407 KV tokens.

Replacement pre-generation KV attempt 2 tested memory utilizations `[0.61733, 0.61613, 0.61508]`. The three completed probes reported KV caches `[0.53, 0.42, 0.32]` GiB, `[23, 98, 113]` preemptions and successful-request p95 latency `[8.21, 15.23, 37.88]` seconds. All 379 requests succeeded in each probe. Commit `3fea48a` selected those three values before r2 generation; these are calibration measurements, not development or test benchmark results.

Recorded development case `inc-17` at memory utilization `0.61613` had successful-request p95 latency 26.08 s in its 30–360 s window, versus 6.45 s for the reference at 30–180 s. Mean queue length was 53.87, maximum queue length 92, p95 KV occupancy 99.67%, and the first-to-last sampled preemption counter increased by 508. The window contained 0 failed outcomes and 0 telemetry-source errors. This is observed development pressure; the pre-generation probe values above remain separate calibration evidence.

The original GPU measured 6 requests/s: p95 latency at 2, 4, 6 and 8 requests/s was 5.54, 7.34, 6.76 and 11.36 seconds. Those measurements describe the original hardware only. They are retained in `provenance/original-hardware-calibration-successful/`.

The original base engine reported 27.35 GiB KV memory and 549,809 KV tokens. Before the original study generation, memory utilizations changed from `[0.8, 0.78, 0.76]` to `[0.727, 0.684, 0.655]`. All three starts passed, reporting 10.92, 6.83 and 4.08 GiB KV memory, about 40%, 25% and 15% of that base.

The initial development KV incident at 0.684 had no service effect: all 1,105 requests succeeded, p95 latency was 6.47 seconds versus 6.31 seconds for the reference, there was no queueing or preemption, and maximum KV occupancy was 9.59%. The initial study remains in `provenance/superseded-development-study/`.

On the original GPU, development-only 90-second probes at `[0.6165, 0.6155, 0.6147]` all started. They reported 8,475 / 6,564 / 5,037 KV tokens and 23 / 45 / 88 preemptions. Successful-request p95 latency was 8.54 / 14.80 / 33.68 seconds. Those values became the severities for the original KV2 study before any test recording or results. They are retained as development severity calibration. The replacement study uses its own pre-generation measurements above.

One rule threshold changed on development data: `surge_arrival_ratio` rose from 1.2 to 1.5. A normal Poisson burst in the batch-limit dev incident had an arrival ratio of 1.322, a four-sequence cap, growing queue and high latency; the original surge branch proposed harmful shedding. The higher threshold restored the batch diagnosis while the real dev surge ratio of 3.391 still triggered. Scoring rules, prompts and answer keys were not changed.

## Evaluation settings and integration changes

The replay diagnosis needed 3,259 input tokens plus a 2,048-token output
allowance (5,307 total), so the dedicated Glimmer evaluation server used an
8,192-token context. The monitor used 2,758 input plus 600 output tokens.
Recording and live engine contexts remained unchanged. A context fault can make
the local monitor fail; that failure is retained and the expert receives the
same observation once under the frozen fallback.

Contention timing was corrected before the final study: asynchronous enqueue
timing had made nominal 50% work duty nearly continuous. The original probe
averaged 95.5% NVML utilization; after synchronization and buffer reuse, a
20-second work window took 21.015 s including startup and averaged 18.7368%
over 19 samples. The replacement preflight took 21.014 s, verified job ownership
and cleaned up. Nominal duty and measured GPU utilization are distinct.
Other pre-freeze integration changes preserved failed checkpoints and engine
restarts, validated credentials, retained monitor failures, and gave each
replay engine its own artifact directory. The context-fixture timing fix did
not change benchmark prompts or traffic.

Spark used `muse-spark-1.3` and Wonder `muse-wonder-1.0`, with
`max_completion_tokens`, `reasoning_effort=low` and temperature 1.0. Rates
rechecked before API2 at `2026-11-02T01:50:15.419666Z` were $1.25/$4.25 per
million Spark input/output tokens and $4/$20 for Wonder. These are historical
accounting rates. Paid requests used a Mac-origin HTTPS CONNECT channel to
`api.meta.ai:443` with end-to-end TLS verification; the relay saw neither Bearer
credentials nor plaintext requests. An unauthenticated HTTP401 established
channel connectivity only; actual recorded completions establish model access.
Catalog visibility differed between origins and later changed; these
observations do not establish the cause of the earlier HTTP404 or a stable
regional policy. The OS CA bundle resolved a local trust-store failure without
disabling certificate verification.

## Development scoreboard

Seven faulty incidents and one healthy control per arm:

| Arm | Detected | False alarms | Correct diagnosis | Safe fix proposed | Harmful | Invalid outputs | Failed calls | Median detection s | API calls | API USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rules | 7 | 0 | 7 | 7 | 0 | 0 | 0 | 30 | 0 | 0.0 |
| glimmer | 7 | 0 | 7 | 7 | 0 | 0 | 0 | 30 | 0 | 0.0 |
| spark | 7 | 0 | 7 | 7 | 0 | 0 | 0 | 30 | 31 | 0.1665 |
| wonder | 7 | 0 | 7 | 7 | 0 | 0 | 0 | 30 | 31 | 0.5823 |
| glimmer_to_spark | 6 | 0 | 6 | 6 | 0 | 0 | 0 | 30 | 6 | 0.0363 |
| glimmer_to_wonder | 6 | 0 | 6 | 6 | 0 | 0 | 0 | 30 | 6 | 0.1509 |

## Test scoreboard

Thirteen faulty incidents and three healthy controls per arm. All six arms
completed the 16 test cases (96 final decision files) by
`2026-11-02T06:12:14Z`. The final development/test package contains 144 decisions.
Median detection is measured only on detected faulty incidents. Wonder's one
invalid test output is retained in its checkpoint journal and cost accounting.

| Arm | Detected | False alarms | Correct diagnosis | Safe fix proposed | Harmful | Invalid outputs | Failed calls | Median detection s | API calls | API USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rules | 12 | 0 | 11 | 11 | 0 | 0 | 0 | 30 | 0 | 0.0 |
| glimmer | 13 | 0 | 13 | 13 | 0 | 0 | 0 | 30 | 0 | 0.0 |
| spark | 13 | 0 | 13 | 13 | 0 | 0 | 0 | 30 | 74 | 0.4021 |
| wonder | 13 | 0 | 13 | 13 | 0 | 1 | 0 | 30 | 74 | 1.4157 |
| glimmer_to_spark | 11 | 0 | 11 | 11 | 0 | 0 | 0 | 30 | 11 | 0.0693 |
| glimmer_to_wonder | 11 | 0 | 11 | 11 | 0 | 0 | 0 | 30 | 11 | 0.2546 |

## Live recovery and shedding

The canonical `recovered` flag checks successful-request latency and
admitted-request errors, excluding the 5% shed cap. `time_to_recover_s` is
onset-relative: the end of the first passing retrospective 30-second window
scanned every 10 seconds, conditional on canonical recovery. It is not time
since the repair. The stored `fault_window_before_action` includes action and
restart time; `after_action` can include rollback. The canonical lagged online
verification window's exact bounds were not persisted and are not assumed
identical to the descriptive window below.

The predeclared descriptive pre cohort is
`[max(public_onset_s, triggering_checkpoint_s - 60), triggering_checkpoint_s)`;
the post cohort is `[action_completion_s + 30, action_completion_s + 90)`.
Membership uses scheduled arrival `t_sched`. Pre-trigger requests may complete
during intervention, so their latency/errors do not isolate completions before
the action. N/offered means persisted outcomes; no missing arrivals are inferred.
The audit reports exact counts and target flags without changing canonical
scores. A missing verification window is inconclusive; an already-passing
window alone does not demonstrate restoration.

Both arms had canonical recovery true for 5, false for 1 and inconclusive for
0 of 6 runs. The full post target (p95 ≤ 10 s, admitted errors ≤ 1%, shedding
≤ 5%) was met in 4/6 cascade runs and 3/6 rules runs. All 12 descriptive pre
cohorts failed that full target, subject to the in-flight-request caveat above.

| Case | Arm | Canonical recovery | Recovery s from onset | Rollback flag | Post N | Post p95 s | Post error % | Post shed / N | Full post target |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| inc-02 | glimmer_to_spark | True | 203.0 | False | 252 | 6.43 | 0.00 | 0/252 (0.00%) | True |
| inc-02 | rules | True | 88.0 | False | 260 | 6.89 | 0.00 | 0/260 (0.00%) | True |
| inc-04 | glimmer_to_spark | True | 102.3 | False | 234 | 6.26 | 0.00 | 0/234 (0.00%) | True |
| inc-04 | rules | True | 97.7 | False | 235 | 6.17 | 0.00 | 0/235 (0.00%) | True |
| inc-05 | glimmer_to_spark | True | 108.4 | False | 240 | 5.97 | 0.00 | 0/240 (0.00%) | True |
| inc-05 | rules | False | — | True | 239 | — | 100.00 | 0/239 (0.00%) | False |
| inc-06 | glimmer_to_spark | True | 96.9 | False | 601 | 6.41 | 0.00 | 361/601 (60.07%) | False |
| inc-06 | rules | True | 80.0 | False | 612 | 6.80 | 0.00 | 230/612 (37.58%) | False |
| inc-09 | glimmer_to_spark | True | 84.0 | False | 242 | 6.24 | 0.00 | 0/242 (0.00%) | True |
| inc-09 | rules | True | 60.2 | False | 244 | 6.76 | 0.00 | 0/244 (0.00%) | True |
| inc-15 | glimmer_to_spark | False | — | True | 265 | 29.65 | 0.00 | 222/265 (83.77%) | False |
| inc-15 | rules | True | 80.0 | False | 249 | 4.77 | 0.00 | 216/249 (86.75%) | False |

The cascade failed and rolled back the long-prompt case: over the full run,
813 requests succeeded, 1,244 timed out and 548 were shed. Rules classified the
batch case as `other` and escalated without applying a service change; 148
requests succeeded and 2,486 timed out. Its rollback flag is bookkeeping,
not an actual undo. Context-fault monitoring and engine restarts also produced
retained HTTP, connection and serving errors. These measured failures remain
part of the result. Gateway latency recovery frequently depended on shedding a
large fraction of offered requests, as the table shows.

## Collection failures, provenance gaps and limits

- The initial paid development attempt had 192 `UnicodeEncodeError` checkpoint
  failures and $9.075474 in conservative reservations, with zero successful
  token-usage responses. The later Wonder HTTP404 retained its partial response
  and $0.063304 reservation. Neither is relabelled as a billed completion or
  silently overwritten. The final evaluation has no failed paid calls.
- Initial tokenizer startup, contention timing, bootstrap and calibration
  summary failures preceded the final study. Superseded ineffective development
  studies remain separate from the final recordings. Only development data
  and pre-generation calibration informed severities and the rule change.
- The first test-batch controller was interrupted; the recorder sealed
  `inc-01` and `inc-06`, then hit `BrokenPipeError`. Its original exit is unknown.
  A continuation recorded only six previously unstarted IDs, adding one engine
  start before `inc-09`; completed recordings were not repeated.
- Original `inc-23` telemetry stopped at second 231 of 360 with `EMFILE`, but
  the frozen recorder incorrectly marked it completed. The original 232 rows
  and status are retained separately as unusable. Before test model evaluation,
  a fresh recording kept the scenario, seed, arrivals and windows unchanged,
  raising only inherited `RLIMIT_NOFILE` soft headroom from 1,024 to 65,536
  (hard limit 1,048,576). The 4,667-outcome replacement was adopted at
  `2026-11-02T04:58:01.632585Z` based on structural completeness, not latency or
  model performance. All 25 recordings and 175 sealed payload hashes passed
  collection checks; the other 24 recording manifests stayed unchanged.
- A later collector-failure propagation fix, historical commit `da5596d`,
  passed 302 tests with one skip and was **not used for frozen measurements**.
  The earlier draft had a late-writer race and remains superseded. Frozen
  source `a0b4deb` passed 289 tests with one skip before API2 evaluation.
- The original-host migration lacked an independently observed remote ledger
  digest. The final replacement mirror did capture one. A premature audit,
  timed-out per-file SCP and unsupported extraction keyword all failed
  explicitly. A subsequent validated extraction of the same archive matched
  the historical 543-file / 51,088,775-byte remote snapshot and canonical ledger;
  no model or recording was rerun. That historical snapshot count does not
  describe the curated public subset.

Final v0 accounting was **Meta $12.255891**, Baseten $0, across 443 records:
$3.117113 settled usage and $9.138778 retained reservations. The canonical ledger
SHA256 was `13f777ed328bb0c71bb2063b6b12cf3b6cb8024d78b0ab46b9e374521a566123`.
The historical GPU estimate was 14.302195 running hours and an upper estimate
of $25.900104 including disk, network and slack reserves. These are cumulative
accounting estimates, not reconciled provider invoices; Hard's later snapshot
includes additional work.

The rules were written by the fault designers and tuned on development data,
so they are an optimistic baseline. This study covers one final GPU, one pinned
engine and one model revision, using a math workload. No statistical significance,
generalization or agent-superiority claim is made.

## Public package scope

The public package keeps incident and live telemetry, request outcomes, sealed
answers, decisions, study commitments, reports and scientific failure evidence.
Internal operator scripts, runbooks, dispatch records and rental administration
were moved to a separate private development archive. Scientific payload bytes
are unchanged. [curation.json](curation.json) records the curation and
[package-manifest.json](package-manifest.json) hashes the current public subset.
Historical reports and freeze descriptors can cite private or unavailable
operational files; this release does not assert closure of the old full
operator package or that every originally packaged file remains public.
