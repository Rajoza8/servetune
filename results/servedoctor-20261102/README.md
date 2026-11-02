# ServeDoctor: GPU incident study

On the held-out test split, the frozen `glimmer_to_spark` arm proposed 11/13 correct fixes versus 11/13 for `rules`, with 0 versus 0 harmful proposals. These are measurements on one GPU, one engine and one model; they do not establish general superiority.

Six selected live runs: the canonical latency/error recovery flag was true for 5, false for 1 and null/inconclusive for 0 of 6 runs. That flag excludes shedding. The separate descriptive 30–90 s post-action windows met the full configured latency/error/shedding target in 4/6 runs; 2 failed that target and 0 were inconclusive. Meeting a post-window target alone does not establish restoration from a failing pre-window. `t_sched` defines arrival-cohort membership; in-flight pre-trigger requests can finish after an action begins, so these cohorts alone do not establish causal restoration.

- `inc-06`: canonical flag `True`; full post target `False`; rollback `False`; post shed 361/601 persisted outcomes (60.07%); successful-request p95 6.41 s.
- `inc-15`: canonical flag `False`; full post target `False`; rollback `True`; post shed 222/265 persisted outcomes (83.77%); successful-request p95 29.65 s.

The final study uses one verified, on-demand Vast RTX PRO 6000 Blackwell Workstation Edition GPU with 96 GB advertised memory (97,887 MiB reported by NVML), GPU UUID `GPU-549b0b27-6ca2-2fca-e5aa-a0f67a43b81b`, compute capability 12.0, and 150 GB disk. Instance `58716527` is on machine `140625`; its actual driver is `580.159.03`. Runtime pins are Python `3.12.3`, PyTorch `2.13.0+cu130`, and vLLM `0.26.1rc1.dev608+g99a10304d`, using image `vastai/vllm@sha256:d17aa376347c086ce53d9f9ac3a70e904acbc37882a7ee0b1ba4f7f538f8d843`.

The original instance `58690026` could not restart because its resources were unavailable. The user authorized replacement and a complete rerun. Its deletion was confirmed at `2026-11-01T21:25:06Z` before the new instance was created. Original-hardware studies and failures remain separately labeled provenance. The healthy reference and eight development recordings originated in `runs/sd-study-r2` and were copied unchanged into `runs/sd-study-r2-api2`. Test recording began directly in API2; the explicit incident 23 repair originates in a new scratch directory as described below. Live phases use API2. Those recordings are not inherited from r2.

The model is `meta-models/Muse-Glimmer-30B` in BF16. Both model and tokenizer are pinned to `cec94fcfd6512f2cfe708138c32533b346ea4f69`. Offline Hugging Face snapshot resolution preserves the pin. The driver differs from historical ServeTune v4; the actual versions above describe this study.

## Study and commitments

Final study: `runs/sd-study-r2-api2`. Experiment frozen at `2026-11-02T02:15:20.469452+00:00` on source `a0b4deb6e9545b9d21fde472ad4686645b083bc6`; freeze-file SHA-256 `7428210756fe9d61599d13f2182416b916f1a43627d178030f73f071b6845319`. The generation and inherited checkpoint commitments are recorded below.

The frozen experiment source is `a0b4deb6e9545b9d21fde472ad4686645b083bc6`. A later commit publishing the result files is distinct from that source commit. All freeze verification, backup and package gates run before the publication commit; the experiment freeze is not restamped after test recording.

`runs/sd-study-r2` was generated at `2026-11-01T22:52:54.909387Z` from commit `3fea48a84cec07231f3a658f57ccc7b125eda8ae`, after replacement KV calibration and before any test recording or results. Its generation commitment records answer-key hash `89af5cbf353c4427b3bacb6b80cef2cacb9b7361db00b21f11a32efeeea7a79a` and scenario hash `51ef576470c93bb68f7fc2a1d22569356ed8b80f113904a031bcc68501e52ca2`. The development selection was bound by the experiment freeze before test recording.

The first r2 Wonder call returned HTTP404 and halted paid evaluation. A new evaluation directory, `runs/sd-study-r2-api2`, was created at `2026-11-02T01:54:09.520580Z` from commit `a0b4deb6e9545b9d21fde472ad4686645b083bc6`. It inherited nine sealed recordings, nine opaque runtime files and 24 completed rules/Spark/Glimmer decisions by binary copy and hash verification. The failed Wonder partial remains in the original r2 history; it was not copied as a completed result. The canonical API ledger was retained. Config, rules, scoring, prompts, model IDs and prices remain unchanged; the source change adds explicit Meta transport selection.

The genuine minimum rules/Spark development checkpoint was met at `2026-11-01T23:59:18.800695Z`, before the November 2 noon Eastern deadline. API2 inherits that exact report through `evaluation-copy-lineage.json` and `lineage/genuine-minimum-checkpoint.json`, bound to SHA-256 `6e3af6b0870527db8084fe86ca0063c0990bbb20658a1dbad867b02ede497bf9`. The original checkpoint marker was not renamed or rewritten.

The final study contains one healthy reference, eight development incidents and sixteen test incidents. Each arm receives the same observation built from telemetry available at that checkpoint. First incident decisions are final. The live escalation arm and six test incident IDs were selected using development results and frozen before test recording.

Test recording was predeclared as two batches of eight incident IDs in `test-recording-batches.json`, using the same canonical `record --split test --ids ...` command. Sixteen incidents require 96 minutes of workload plus up to 24 minutes of drain time, which risks the 117-minute work cap before startup and mirroring. Two phases add one engine startup and mirror without changing any incident, arrival schedule, duration, observation, prompt, severity or scoring rule. The original plan was transferred and its remote SHA-256 verified before any test directory existed, with hash `fd0e9ad1fbc954c1c46752f43d2ffc03149b67a86ec8cd9ee294869e478aa182`. API2 rebinds only its study path and source commit, preserving the identical IDs and measurement policy; the rebound plan hash is `6ed28c97bd2a330329c091c660c924d0d823ca5176cfc210804986e4b876d6f3`. The experiment freeze binds that plan. Batch phases use the already held GPU.

Selected at `2026-11-02T02:15:20.026672+00:00`: `glimmer_to_spark`. Predeclared policy: Higher fixes, lower harm, higher diagnosis, lower false alarms, higher detection, lower cost; final tie Spark. Declared before dev results.

| Fault type | Frozen test ID |
| --- | --- |
| `kv_cache_starvation` | `inc-02` |
| `context_limit_too_small` | `inc-04` |
| `batch_limit_too_low` | `inc-05` |
| `traffic_surge` | `inc-06` |
| `gpu_contention` | `inc-09` |
| `long_prompt_flood` | `inc-15` |

The two escalation arms had these recorded development results:

```json
{
  "glimmer_to_spark": {
    "incidents": 7,
    "healthy_controls": 1,
    "detected": 6,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 6,
    "fix_proposed": 6,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 6,
    "api_cost_usd": 0.0363
  },
  "glimmer_to_wonder": {
    "incidents": 7,
    "healthy_controls": 1,
    "detected": 6,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 6,
    "fix_proposed": 6,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 6,
    "api_cost_usd": 0.1509
  }
}
```

## Capacity and development calibration

Replacement calibration ran 60-second steps at 2, 4, 6, 8 and 10 requests/s and stopped at the first SLO violation. Successful-request p95 latency was 5.44, 6.77, 6.32, 9.02 and 18.48 seconds respectively, with no failed requests. Measured capacity is 8 requests/s under the 10-second latency SLO and 1% error cap. The completed 10 requests/s step exceeded the latency SLO. The replacement base engine at `gpu_memory_utilization=0.9` reported 27.38 GiB KV memory and 550,407 KV tokens.

Replacement pre-generation KV attempt 2 tested memory utilizations `[0.61733, 0.61613, 0.61508]`. The three completed probes reported KV caches `[0.53, 0.42, 0.32]` GiB, `[23, 98, 113]` preemptions and successful-request p95 latency `[8.21, 15.23, 37.88]` seconds. All 379 requests succeeded in each probe. Commit `3fea48a` selected those three values before r2 generation; these are calibration measurements, not development or test benchmark results.

Recorded development case `inc-17` at memory utilization `0.61613` had successful-request p95 latency 26.08 s in its 30–360 s window, versus 6.45 s for the reference at 30–180 s. Mean queue length was 53.87, maximum queue length 92, p95 KV occupancy 99.67%, and the first-to-last sampled preemption counter increased by 508. The window contained 0 failed outcomes and 0 telemetry-source errors. This is observed development pressure; the pre-generation probe values above remain separate calibration evidence.

The original GPU measured 6 requests/s: p95 latency at 2, 4, 6 and 8 requests/s was 5.54, 7.34, 6.76 and 11.36 seconds. Those measurements describe the original hardware only. They are retained in `provenance/original-hardware-calibration-successful/`.

The original base engine reported 27.35 GiB KV memory and 549,809 KV tokens. Before the original study generation, memory utilizations changed from `[0.8, 0.78, 0.76]` to `[0.727, 0.684, 0.655]`. All three starts passed, reporting 10.92, 6.83 and 4.08 GiB KV memory, about 40%, 25% and 15% of that base.

The initial development KV incident at 0.684 had no service effect: all 1,105 requests succeeded, p95 latency was 6.47 seconds versus 6.31 seconds for the reference, there was no queueing or preemption, and maximum KV occupancy was 9.59%. The initial study remains in `provenance/superseded-development-study/`.

On the original GPU, development-only 90-second probes at `[0.6165, 0.6155, 0.6147]` all started. They reported 8,475 / 6,564 / 5,037 KV tokens and 23 / 45 / 88 preemptions. Successful-request p95 latency was 8.54 / 14.80 / 33.68 seconds. Those values became the severities for the original KV2 study before any test recording or results. They are retained as development severity calibration. The replacement study uses its own pre-generation measurements above.

One rule threshold changed on development data: `surge_arrival_ratio` rose from 1.2 to 1.5. A normal Poisson burst in the batch-limit dev incident had an arrival ratio of 1.322, a four-sequence cap, growing queue and high latency; the original surge branch proposed harmful shedding. The higher threshold restored the batch diagnosis while the real dev surge ratio of 3.391 still triggered. Scoring rules, prompts and answer keys were not changed.

## Runtime integration changes

| Commit | Change and reason |
| --- | --- |
| `a2cf73e` | Halt at the ledger's 50% warning, retain incomplete paid checkpoints, and reject unpriced Baseten calls. |
| `b5c2b50` | Preserve GPU and live failures, reject failed or contaminated recordings, and restore prior configuration after a failed engine restart. |
| `0bd22ff` | Restore the v4 offline cache environment after online resolution caused worker revision drift and tokenizer failure. |
| `9dd15a8` | Synchronize completed contention iterations and reuse buffers; asynchronous enqueue timing had made nominal 50% duty nearly continuous GPU work. |
| `d49fad1` | Calibrate initial KV severities to successful starts with about 40%, 25% and 15% of base cache. |
| `ab670de` | Give replay evaluation an 8,192-token Glimmer context and each evaluation engine a fresh artifact directory. Incident and live engine contexts remain frozen. |
| `aedc7d9` | Retain failed local monitor calls and escalate the same observation once; journal permanent paid HTTP rejections and halt without retrying. |
| `1be578f` | Tune the arrival-ratio rule on dev to avoid harmful batch-limit misdiagnosis. |
| `ea9c294` | Replace ineffective initial KV severities using the isolated development pressure probes; preserve the superseded study. |
| `d95f4a6` | Validate paid credentials before dispatch and halt on transport encoding errors after preserving one failed checkpoint. |
| `092a5ca` | Remove a timing race from the context-fault test fixture by ensuring an oversized request precedes its first checkpoint. Benchmark prompts and traffic are unchanged. |
| `cf0d6cb` | Clean up each acquired live-run resource after setup failures, preserve the original exception and retain failure artifacts. |
| `3fea48a` | Select replacement-specific KV severities from the completed pre-generation pressure probes. |
| `a0b4deb` | Add an explicit study-scoped Meta HTTP CONNECT transport with numeric-loopback validation, instance binding, fixed official host and verified end-to-end TLS. |

On the original GPU, the nominal 50% contention probe averaged 95.5% GPU utilization. After the timing fix, a 20-second requested work window completed in 21.015 seconds including startup and averaged 18.7368% NVML utilization over 19 samples at elapsed seconds 3–21. On the replacement, the same owned-process preflight completed its requested 20-second work window in 21.014 seconds; the local PID and ownership marker were verified and cleanup completed. Nominal work duty and measured NVML utilization are distinct.

The pinned tokenizer measured 3,259 input tokens plus a 2,048-token output allowance for a full reference diagnosis: 5,307 total, exceeding the original 4,096-token replay context. The dedicated replay server therefore uses 8,192 tokens. The corresponding monitor used 2,758 input plus 600 output tokens, or 3,358 total. A live context fault can still make its serving model unavailable for monitoring; the failed monitor call is retained and the expert receives the same observation once.

The [official Meta pricing](https://dev.meta.ai/docs/pricing-rate-limits), [models](https://dev.meta.ai/docs/models) and [Chat Completions protocol](https://dev.meta.ai/docs/protocols/chat-completions) were rechecked before paid replacement-hardware evaluation; prices were reverified at `2026-11-02T01:50:15.419666Z` before the fresh API2 attempt. Wonder is `muse-wonder-1.0` at $4 input and $20 output per million tokens; Spark is `muse-spark-1.3` at $1.25 input and $4.25 output. Requests use `max_completion_tokens`, `reasoning_effort=low` and temperature 1.0. The Wonder environment override resolves its documented ID; ledger rates did not change. Credentials are excluded from this package.

Vast locates the replacement host in South Korea, where Meta's model documentation states Wonder is unavailable. The earlier direct GPU catalog omitted Wonder while the operator Mac catalog included it. A later direct check included Wonder from both origins. Those observations do not establish why the first call returned HTTP404 or prove a stable regional enforcement mechanism. All three filtered diagnostics and the catalog-transition record remain preserved.

Fresh API2 Meta evaluations used the explicit Mac-origin CONNECT transport consistently; live Meta calls follow that same configuration. `api-transport.json` selects a numeric-loopback proxy bound to instance `58716527`; TLS still terminates at `api.meta.ai`, with the same official HTTPS URL, models, request bodies and prices. The relay sees no Bearer credential or plaintext request body. An unauthenticated GET returned HTTP401 through the channel with TLS verification enabled, proving the channel only. Local authenticated catalog evidence establishes model visibility; successful completion outcomes must come from the actual recorded calls. The local Python CA failure was repaired using the reviewed OS trust bundle without disabling verification.

## Development scoreboard

Output from `python3 -m servedoctor score --study-dir runs/sd-study-r2-api2 --split dev`:

```json
{
  "glimmer": {
    "incidents": 7,
    "healthy_controls": 1,
    "detected": 7,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 7,
    "fix_proposed": 7,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 0,
    "api_cost_usd": 0.0
  },
  "glimmer_to_spark": {
    "incidents": 7,
    "healthy_controls": 1,
    "detected": 6,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 6,
    "fix_proposed": 6,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 6,
    "api_cost_usd": 0.0363
  },
  "glimmer_to_wonder": {
    "incidents": 7,
    "healthy_controls": 1,
    "detected": 6,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 6,
    "fix_proposed": 6,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 6,
    "api_cost_usd": 0.1509
  },
  "rules": {
    "incidents": 7,
    "healthy_controls": 1,
    "detected": 7,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 7,
    "fix_proposed": 7,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 0,
    "api_cost_usd": 0.0
  },
  "spark": {
    "incidents": 7,
    "healthy_controls": 1,
    "detected": 7,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 7,
    "fix_proposed": 7,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 31,
    "api_cost_usd": 0.1665
  },
  "wonder": {
    "incidents": 7,
    "healthy_controls": 1,
    "detected": 7,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 7,
    "fix_proposed": 7,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 31,
    "api_cost_usd": 0.5823
  }
}
```

## Test scoreboard

All six replay arms completed the 16 test cases, producing 96 final test decision files, at `2026-11-02T06:12:14Z`. The exact CLI development and test scoreboards are retained in `provenance/operations/test-checkpoint-report-20261102T062545Z.json`; all 25 canonical recordings had passed structural collection quality after the single explicit incident 23 adoption, with 169 frozen hashes and the other 24 manifest hashes unchanged. Replay completion does not establish live recovery or fixed final spend.

Output from `python3 -m servedoctor score --study-dir runs/sd-study-r2-api2 --split test`:

```json
{
  "glimmer": {
    "incidents": 13,
    "healthy_controls": 3,
    "detected": 13,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 13,
    "fix_proposed": 13,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 0,
    "api_cost_usd": 0.0
  },
  "glimmer_to_spark": {
    "incidents": 13,
    "healthy_controls": 3,
    "detected": 11,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 11,
    "fix_proposed": 11,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 11,
    "api_cost_usd": 0.0693
  },
  "glimmer_to_wonder": {
    "incidents": 13,
    "healthy_controls": 3,
    "detected": 11,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 11,
    "fix_proposed": 11,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 11,
    "api_cost_usd": 0.2546
  },
  "rules": {
    "incidents": 13,
    "healthy_controls": 3,
    "detected": 12,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 11,
    "fix_proposed": 11,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 0,
    "api_cost_usd": 0.0
  },
  "spark": {
    "incidents": 13,
    "healthy_controls": 3,
    "detected": 13,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 13,
    "fix_proposed": 13,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 0,
    "call_failures": 0,
    "api_calls": 74,
    "api_cost_usd": 0.4021
  },
  "wonder": {
    "incidents": 13,
    "healthy_controls": 3,
    "detected": 13,
    "false_alarms": 0,
    "healthy_false_alarms": 0,
    "diagnosis_correct": 13,
    "fix_proposed": 13,
    "harmful": 0,
    "median_time_to_detect_s": 30,
    "invalid_outputs": 1,
    "call_failures": 0,
    "api_calls": 74,
    "api_cost_usd": 1.4157
  }
}
```

## Live recovery

The canonical `recovered` flag checks successful-request latency and admitted-request errors; it does not check the shed-rate cap. The stored `fault_window_before_action` summary includes the action/restart interval, and `after_action` can include rollback. `time_to_recover_s` is measured from fault onset. A separate predeclared descriptive audit reports exact pre-trigger and post-action 30–90 s scheduled-arrival cohorts, actual request and shed counts, and flags for pre-onset action or windows that were already within SLO. Those flags do not change canonical metrics or scoring; missing evidence is inconclusive, and two already-passing windows do not demonstrate restoration. The descriptive pre window is `[max(public_onset_s, triggering_checkpoint_s - 60), triggering_checkpoint_s)`; the post window is `[action_completion_s + 30, action_completion_s + 90)`, using persisted requests grouped by `t_sched`. `N`/offered counts persisted outcomes and does not infer unpersisted arrivals. The canonical stored `post_fix_window` comes from a lagged online check; its exact bounds were not persisted and are not assumed identical to the descriptive post window.

The descriptive pre window is a pre-trigger scheduled-arrival cohort: membership uses `t_sched`. Requests in that cohort can still be in flight when an action or restart begins, and their later completion latency or error can include intervention effects. The cohort therefore does not isolate requests completed before intervention. Post-window membership also uses scheduled arrival time. These windows describe the recorded request cohorts; they alone do not establish that an action caused service restoration.

Selected escalation runs: the canonical latency/error recovery flag was true for 5, false for 1 and null/inconclusive for 0 of 6 runs. That flag excludes shedding. The separate descriptive 30–90 s post-action windows met the full configured latency/error/shedding target in 4/6 runs; 2 failed that target and 0 were inconclusive. Meeting a post-window target alone does not establish restoration from a failing pre-window. `t_sched` defines arrival-cohort membership; in-flight pre-trigger requests can finish after an action begins, so these cohorts alone do not establish causal restoration.

- `inc-06`: canonical flag `True`; full post target `False`; rollback `False`; post shed 361/601 persisted outcomes (60.07%); successful-request p95 6.41 s.
- `inc-15`: canonical flag `False`; full post target `False`; rollback `True`; post shed 222/265 persisted outcomes (83.77%); successful-request p95 29.65 s.

Predeclared descriptive plan SHA-256: `68d027631715fc7862bc8e2299c8ebfd50d0515ce62bf8536b96cae6a1749fee`. Actual audit report SHA-256: `15f9ed3ad4c55316112a04608eb27d28ae25d17081708e1676c7cd8c81a8757d`. Exact window bounds, persisted-outcome N/offered/ok/failed/shed/admitted counts, target flags and limitations are quoted below. The audit does not infer unpersisted offered arrivals or change canonical scores.

```json
[
  {
    "id": "inc-02",
    "run_directory": "runs/sd-study-r2-api2/live/inc-02-glimmer_to_spark-20261102t062614054348z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 203.0,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 684,
        "ok": 484,
        "shed": 0,
        "failed": 200,
        "shed_rate": 0.0,
        "error_rate": 0.29239766081871343,
        "p50_latency_s": 5.803542042616755,
        "p95_latency_s": 10.891690712329
      },
      "after_action": {
        "requests": 1945,
        "ok": 1945,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.7128557385876775,
        "p95_latency_s": 6.417596042342484
      },
      "verification_window": {
        "requests": 256,
        "ok": 256,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.853782661724836,
        "p95_latency_s": 6.4258493857923895
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 37.70984926726669,
    "engine_restarts": [
      {
        "knob": "gpu_memory_utilization",
        "value": 0.9,
        "status": "completed",
        "seconds": 37.70984926726669
      }
    ],
    "executed_actions": [
      {
        "action": {
          "type": "set_engine_config",
          "knob": "gpu_memory_utilization",
          "value": 0.9
        },
        "at": "2026-11-02T06:29:14.288323+00:00",
        "previous": {
          "gpu_memory_utilization": 0.61733
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-02",
      "arm": "glimmer_to_spark",
      "run_directory": "runs/sd-study-r2-api2/live/inc-02-glimmer_to_spark-20261102t062614054348z",
      "anchors": {
        "public_onset_s": 0.0,
        "triggering_checkpoint_s": 120.0,
        "action_completion_s": 173.0,
        "action_starts_s_approximate": [
          135.280121
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 60.0,
        "end_s": 120.0,
        "length_s": 60.0,
        "N": 214,
        "offered": 214,
        "ok": 214,
        "failed": 0,
        "shed": 0,
        "admitted": 214,
        "p95_latency_s": 11.245819673733784,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 203.0,
        "end_s": 263.0,
        "length_s": 60.0,
        "N": 252,
        "offered": 252,
        "ok": 252,
        "failed": 0,
        "shed": 0,
        "admitted": 252,
        "p95_latency_s": 6.427229600818828,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": true,
        "full_configured_target_met": true,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 203.0,
        "acted_at_s": 173.0,
        "fault_window_before_action": {
          "requests": 684,
          "ok": 484,
          "shed": 0,
          "failed": 200,
          "shed_rate": 0.0,
          "error_rate": 0.29239766081871343,
          "p50_latency_s": 5.803542042616755,
          "p95_latency_s": 10.891690712329
        },
        "after_action": {
          "requests": 1945,
          "ok": 1945,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.7128557385876775,
          "p95_latency_s": 6.417596042342484
        },
        "post_fix_window": {
          "requests": 256,
          "ok": 256,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.853782661724836,
          "p95_latency_s": 6.4258493857923895
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "set_engine_config",
          "status": "executed",
          "knob": "gpu_memory_utilization",
          "value": 0.9
        }
      ],
      "restarts": {
        "entries": [
          {
            "knob": "gpu_memory_utilization",
            "value": 0.9,
            "status": "completed",
            "seconds": 37.70984926726669,
            "phase": "forward"
          }
        ],
        "seconds": {
          "forward": 37.70984926726669,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": false
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "f4081b5ed6098cc9ed94d55c4cf2b958fa8fce8fe8caf55eef9d90ebca8739ff",
        "checkpoints.jsonl": "bf24786eeee356523dc58a1b56fdea5fc91bfcd432e3aa5095255cac7df0224b",
        "requests.jsonl": "8b35b7bffa7a1a07f86a2bf28619c3138e7b97ddd573f05d8fb47bb228d9af1d",
        "scenario_public.json": "43039476a2f71c736eb99f83ff5259a0ef4ec7c1a8d22cd77da040c0d749c3ac"
      }
    }
  },
  {
    "id": "inc-04",
    "run_directory": "runs/sd-study-r2-api2/live/inc-04-glimmer_to_spark-20261102t062614054348z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 102.3,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 249,
        "ok": 86,
        "shed": 0,
        "failed": 163,
        "shed_rate": 0.0,
        "error_rate": 0.6546184738955824,
        "p50_latency_s": 4.850101901218295,
        "p95_latency_s": 4.9555855062790215
      },
      "after_action": {
        "requests": 2292,
        "ok": 2292,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.704381673131138,
        "p95_latency_s": 6.39325197506696
      },
      "verification_window": {
        "requests": 218,
        "ok": 218,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.930124916601926,
        "p95_latency_s": 6.602378861932084
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 37.68654798809439,
    "engine_restarts": [
      {
        "knob": "max_model_len",
        "value": 4096,
        "status": "completed",
        "seconds": 37.68654798809439
      }
    ],
    "executed_actions": [
      {
        "action": {
          "type": "set_engine_config",
          "knob": "max_model_len",
          "value": 4096
        },
        "at": "2026-11-02T06:39:42.611251+00:00",
        "previous": {
          "max_model_len": 768
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-04",
      "arm": "glimmer_to_spark",
      "run_directory": "runs/sd-study-r2-api2/live/inc-04-glimmer_to_spark-20261102t062614054348z",
      "anchors": {
        "public_onset_s": 0.0,
        "triggering_checkpoint_s": 30.0,
        "action_completion_s": 72.3,
        "action_starts_s_approximate": [
          34.62276
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 0.0,
        "end_s": 30.0,
        "length_s": 30.0,
        "N": 104,
        "offered": 104,
        "ok": 84,
        "failed": 20,
        "shed": 0,
        "admitted": 104,
        "p95_latency_s": 4.9538529881741855,
        "error_rate": 0.19230769230769232,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 102.3,
        "end_s": 162.3,
        "length_s": 60.000000000000014,
        "N": 234,
        "offered": 234,
        "ok": 234,
        "failed": 0,
        "shed": 0,
        "admitted": 234,
        "p95_latency_s": 6.260686358995736,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": true,
        "full_configured_target_met": true,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 102.3,
        "acted_at_s": 72.3,
        "fault_window_before_action": {
          "requests": 249,
          "ok": 86,
          "shed": 0,
          "failed": 163,
          "shed_rate": 0.0,
          "error_rate": 0.6546184738955824,
          "p50_latency_s": 4.850101901218295,
          "p95_latency_s": 4.9555855062790215
        },
        "after_action": {
          "requests": 2292,
          "ok": 2292,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.704381673131138,
          "p95_latency_s": 6.39325197506696
        },
        "post_fix_window": {
          "requests": 218,
          "ok": 218,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.930124916601926,
          "p95_latency_s": 6.602378861932084
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "set_engine_config",
          "status": "executed",
          "knob": "max_model_len",
          "value": 4096
        }
      ],
      "restarts": {
        "entries": [
          {
            "knob": "max_model_len",
            "value": 4096,
            "status": "completed",
            "seconds": 37.68654798809439,
            "phase": "forward"
          }
        ],
        "seconds": {
          "forward": 37.68654798809439,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [
          "HTTPError"
        ],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": false
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "e5eb3947d9f31ed86dae1969a961b38c027d2b98b4e2f7b7da5dc74152f445bc",
        "checkpoints.jsonl": "f402357e788a1609b6a9e96cb5f631173478ab42f70bfe3bbc89b30cd02e6420",
        "requests.jsonl": "6e89b7f7f9a8c3929d67d69fd4a167a41352382d5da987bb9b451986809e5d06",
        "scenario_public.json": "0432341cd1c4d7d83c10eb77c6af28e3d4ec693d21c06066a79845745180fa0a"
      }
    }
  },
  {
    "id": "inc-05",
    "run_directory": "runs/sd-study-r2-api2/live/inc-05-glimmer_to_spark-20261102t062614054348z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 108.4,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 316,
        "ok": 56,
        "shed": 0,
        "failed": 260,
        "shed_rate": 0.0,
        "error_rate": 0.8227848101265823,
        "p50_latency_s": 13.222890559118241,
        "p95_latency_s": 22.32848303997889
      },
      "after_action": {
        "requests": 2318,
        "ok": 2318,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.718817459885031,
        "p95_latency_s": 6.444423217466102
      },
      "verification_window": {
        "requests": 226,
        "ok": 226,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.641135296784341,
        "p95_latency_s": 5.9607603857293725
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 37.90740461368114,
    "engine_restarts": [
      {
        "knob": "max_num_seqs",
        "value": 64,
        "status": "completed",
        "seconds": 37.90740461368114
      }
    ],
    "executed_actions": [
      {
        "action": {
          "type": "set_engine_config",
          "knob": "max_num_seqs",
          "value": 64
        },
        "at": "2026-11-02T06:51:54.932863+00:00",
        "previous": {
          "max_num_seqs": 8
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-05",
      "arm": "glimmer_to_spark",
      "run_directory": "runs/sd-study-r2-api2/live/inc-05-glimmer_to_spark-20261102t062614054348z",
      "anchors": {
        "public_onset_s": 0.0,
        "triggering_checkpoint_s": 30.0,
        "action_completion_s": 78.4,
        "action_starts_s_approximate": [
          40.533516
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 0.0,
        "end_s": 30.0,
        "length_s": 30.0,
        "N": 120,
        "offered": 120,
        "ok": 56,
        "failed": 64,
        "shed": 0,
        "admitted": 120,
        "p95_latency_s": 22.32848303997889,
        "error_rate": 0.5333333333333333,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 108.4,
        "end_s": 168.4,
        "length_s": 60.0,
        "N": 240,
        "offered": 240,
        "ok": 240,
        "failed": 0,
        "shed": 0,
        "admitted": 240,
        "p95_latency_s": 5.9675158427562565,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": true,
        "full_configured_target_met": true,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 108.4,
        "acted_at_s": 78.4,
        "fault_window_before_action": {
          "requests": 316,
          "ok": 56,
          "shed": 0,
          "failed": 260,
          "shed_rate": 0.0,
          "error_rate": 0.8227848101265823,
          "p50_latency_s": 13.222890559118241,
          "p95_latency_s": 22.32848303997889
        },
        "after_action": {
          "requests": 2318,
          "ok": 2318,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.718817459885031,
          "p95_latency_s": 6.444423217466102
        },
        "post_fix_window": {
          "requests": 226,
          "ok": 226,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.641135296784341,
          "p95_latency_s": 5.9607603857293725
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "set_engine_config",
          "status": "executed",
          "knob": "max_num_seqs",
          "value": 64
        }
      ],
      "restarts": {
        "entries": [
          {
            "knob": "max_num_seqs",
            "value": 64,
            "status": "completed",
            "seconds": 37.90740461368114,
            "phase": "forward"
          }
        ],
        "seconds": {
          "forward": 37.90740461368114,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": false
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "d21b6d1c232f260322c1322e74cc88cd9ca4a7bc7dfe1fa5bc31c47b42eddb0a",
        "checkpoints.jsonl": "3532064bfd0271f23f6993332cf2308f65f7da8648d42ea444bc9b82278bd2d4",
        "requests.jsonl": "940d540bda30a0f887abb2e91c307c3d74ad1d15071c4ee9ded7ae68f16357ba",
        "scenario_public.json": "86eaa3d8e43d142b8d3c9c78b6eb88470cc594e57a812c1c9689c4eacb29bf9f"
      }
    }
  },
  {
    "id": "inc-06",
    "run_directory": "runs/sd-study-r2-api2/live/inc-06-glimmer_to_spark-20261102t062614054348z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 96.9,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 465,
        "ok": 465,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 12.993845683522522,
        "p95_latency_s": 16.55351449474692
      },
      "after_action": {
        "requests": 5128,
        "ok": 1976,
        "shed": 3152,
        "failed": 0,
        "shed_rate": 0.6146645865834633,
        "error_rate": 0.0,
        "p50_latency_s": 5.619250623974949,
        "p95_latency_s": 6.410708062583581
      },
      "verification_window": {
        "requests": 604,
        "ok": 240,
        "shed": 364,
        "failed": 0,
        "shed_rate": 0.6026490066225165,
        "error_rate": 0.0,
        "p50_latency_s": 5.698401402216405,
        "p95_latency_s": 6.342542470432818
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 0,
    "engine_restarts": [],
    "executed_actions": [
      {
        "action": {
          "type": "gateway_rate_limit",
          "max_rps": 4.0
        },
        "at": "2026-11-02T07:06:07.257041+00:00",
        "previous": {
          "max_rps": null,
          "max_prompt_tokens": null
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-06",
      "arm": "glimmer_to_spark",
      "run_directory": "runs/sd-study-r2-api2/live/inc-06-glimmer_to_spark-20261102t062614054348z",
      "anchors": {
        "public_onset_s": 120.0,
        "triggering_checkpoint_s": 150.0,
        "action_completion_s": 166.9,
        "action_starts_s_approximate": [
          166.93747
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 120.0,
        "end_s": 150.0,
        "length_s": 30.0,
        "N": 303,
        "offered": 303,
        "ok": 303,
        "failed": 0,
        "shed": 0,
        "admitted": 303,
        "p95_latency_s": 14.723886274266988,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 196.9,
        "end_s": 256.9,
        "length_s": 59.99999999999997,
        "N": 601,
        "offered": 601,
        "ok": 240,
        "failed": 0,
        "shed": 361,
        "admitted": 240,
        "p95_latency_s": 6.410608993889764,
        "error_rate": 0.0,
        "shed_rate": 0.6006655574043261,
        "latency_error_target_met": true,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 96.9,
        "acted_at_s": 166.9,
        "fault_window_before_action": {
          "requests": 465,
          "ok": 465,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 12.993845683522522,
          "p95_latency_s": 16.55351449474692
        },
        "after_action": {
          "requests": 5128,
          "ok": 1976,
          "shed": 3152,
          "failed": 0,
          "shed_rate": 0.6146645865834633,
          "error_rate": 0.0,
          "p50_latency_s": 5.619250623974949,
          "p95_latency_s": 6.410708062583581
        },
        "post_fix_window": {
          "requests": 604,
          "ok": 240,
          "shed": 364,
          "failed": 0,
          "shed_rate": 0.6026490066225165,
          "error_rate": 0.0,
          "p50_latency_s": 5.698401402216405,
          "p95_latency_s": 6.342542470432818
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "gateway_rate_limit",
          "status": "executed",
          "max_rps": 4.0
        }
      ],
      "restarts": {
        "entries": [],
        "seconds": {
          "forward": 0.0,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": true
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "b1ec473eda23f22093796025a4cc198306cd329878d0b4a9cb4c0b8ddaef1dd7",
        "checkpoints.jsonl": "155418948f5ef8eecf4d9b8f686293f414fe9980ca0a51271982cd2b63edf2b3",
        "requests.jsonl": "13bbc7844eb0f1ee1f48283dfbde59f6013cc5c08bb3707079627e8f23ec4f08",
        "scenario_public.json": "e6b15c337bb4136388b151b11a99c25611abe72b9f5043adca06f3aa8819cd5b"
      }
    }
  },
  {
    "id": "inc-09",
    "run_directory": "runs/sd-study-r2-api2/live/inc-09-glimmer_to_spark-20261102t062614054348z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 84.0,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 224,
        "ok": 224,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 13.134021928999573,
        "p95_latency_s": 15.661682754894718
      },
      "after_action": {
        "requests": 1963,
        "ok": 1963,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.673656173050404,
        "p95_latency_s": 6.560827084351331
      },
      "verification_window": {
        "requests": 234,
        "ok": 234,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.678922787774354,
        "p95_latency_s": 6.2495779161341485
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 0,
    "engine_restarts": [],
    "executed_actions": [
      {
        "action": {
          "type": "stop_gpu_process",
          "pid": 30087
        },
        "at": "2026-11-02T07:18:18.313119+00:00",
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-09",
      "arm": "glimmer_to_spark",
      "run_directory": "runs/sd-study-r2-api2/live/inc-09-glimmer_to_spark-20261102t062614054348z",
      "anchors": {
        "public_onset_s": 120.0,
        "triggering_checkpoint_s": 150.0,
        "action_completion_s": 174.0,
        "action_starts_s_approximate": [
          173.851103
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 120.0,
        "end_s": 150.0,
        "length_s": 30.0,
        "N": 129,
        "offered": 129,
        "ok": 129,
        "failed": 0,
        "shed": 0,
        "admitted": 129,
        "p95_latency_s": 14.700017725117505,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 204.0,
        "end_s": 264.0,
        "length_s": 60.0,
        "N": 242,
        "offered": 242,
        "ok": 242,
        "failed": 0,
        "shed": 0,
        "admitted": 242,
        "p95_latency_s": 6.242505383118986,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": true,
        "full_configured_target_met": true,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 84.0,
        "acted_at_s": 174.0,
        "fault_window_before_action": {
          "requests": 224,
          "ok": 224,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 13.134021928999573,
          "p95_latency_s": 15.661682754894718
        },
        "after_action": {
          "requests": 1963,
          "ok": 1963,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.673656173050404,
          "p95_latency_s": 6.560827084351331
        },
        "post_fix_window": {
          "requests": 234,
          "ok": 234,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.678922787774354,
          "p95_latency_s": 6.2495779161341485
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "stop_gpu_process",
          "status": "executed",
          "pid": 30087
        }
      ],
      "restarts": {
        "entries": [],
        "seconds": {
          "forward": 0.0,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": false
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "64197ad93a475dd7817b92977277f9f577d11a05c50b364432ab8465fba6277d",
        "checkpoints.jsonl": "c0edee7493a26ac8012aad28eda75a9d240d04ad61099858bc4ab445beda3cfb",
        "requests.jsonl": "a4366bef60b626aaa36ca6a78dbf280bdf1262d356fb2cda4c24053e157a7c99",
        "scenario_public.json": "f741f7bdf5d7aac0ef6aff8310dfc131c876452d66f804da2a772f16c4499a27"
      }
    }
  },
  {
    "id": "inc-15",
    "run_directory": "runs/sd-study-r2-api2/live/inc-15-glimmer_to_spark-20261102t062614054348z",
    "outcome": "not recovered",
    "canonical_recovered": false,
    "rolled_back": true,
    "canonical": {
      "recovered": false,
      "time_to_recover_s": null,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 303,
        "ok": 126,
        "shed": 0,
        "failed": 177,
        "shed_rate": 0.0,
        "error_rate": 0.5841584158415841,
        "p50_latency_s": 44.230811616405845,
        "p95_latency_s": 57.94352083327249
      },
      "after_action": {
        "requests": 1845,
        "ok": 230,
        "shed": 548,
        "failed": 1067,
        "shed_rate": 0.2970189701897019,
        "error_rate": 0.8226676946800309,
        "p50_latency_s": 36.0060211699456,
        "p95_latency_s": 54.014486502204086
      },
      "verification_window": {
        "requests": 259,
        "ok": 50,
        "shed": 209,
        "failed": 0,
        "shed_rate": 0.806949806949807,
        "error_rate": 0.0,
        "p50_latency_s": 4.8138682073913515,
        "p95_latency_s": 20.426940206578
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 0,
    "engine_restarts": [],
    "executed_actions": [
      {
        "action": {
          "type": "gateway_max_prompt_tokens",
          "max_prompt_tokens": 1000
        },
        "at": "2026-11-02T07:30:48.033091+00:00",
        "previous": {
          "max_rps": null,
          "max_prompt_tokens": null
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-15",
      "arm": "glimmer_to_spark",
      "run_directory": "runs/sd-study-r2-api2/live/inc-15-glimmer_to_spark-20261102t062614054348z",
      "anchors": {
        "public_onset_s": 120.0,
        "triggering_checkpoint_s": 167.751,
        "action_completion_s": 200.2,
        "action_starts_s_approximate": [
          200.238242
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 120.0,
        "end_s": 167.751,
        "length_s": 47.751000000000005,
        "N": 186,
        "offered": 186,
        "ok": 126,
        "failed": 60,
        "shed": 0,
        "admitted": 186,
        "p95_latency_s": 57.94352083327249,
        "error_rate": 0.3225806451612903,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 230.2,
        "end_s": 290.2,
        "length_s": 60.0,
        "N": 265,
        "offered": 265,
        "ok": 43,
        "failed": 0,
        "shed": 222,
        "admitted": 43,
        "p95_latency_s": 29.646333278901874,
        "error_rate": 0.0,
        "shed_rate": 0.8377358490566038,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": false,
        "rolled_back": true,
        "time_to_recover_s": null,
        "acted_at_s": 200.2,
        "fault_window_before_action": {
          "requests": 303,
          "ok": 126,
          "shed": 0,
          "failed": 177,
          "shed_rate": 0.0,
          "error_rate": 0.5841584158415841,
          "p50_latency_s": 44.230811616405845,
          "p95_latency_s": 57.94352083327249
        },
        "after_action": {
          "requests": 1845,
          "ok": 230,
          "shed": 548,
          "failed": 1067,
          "shed_rate": 0.2970189701897019,
          "error_rate": 0.8226676946800309,
          "p50_latency_s": 36.0060211699456,
          "p95_latency_s": 54.014486502204086
        },
        "post_fix_window": {
          "requests": 259,
          "ok": 50,
          "shed": 209,
          "failed": 0,
          "shed_rate": 0.806949806949807,
          "error_rate": 0.0,
          "p50_latency_s": 4.8138682073913515,
          "p95_latency_s": 20.426940206578
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "gateway_max_prompt_tokens",
          "status": "executed",
          "max_prompt_tokens": 1000
        }
      ],
      "restarts": {
        "entries": [],
        "seconds": {
          "forward": 0.0,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": true
      },
      "inconclusive": false,
      "interpretation": "Post window misses the latency/error target.",
      "public_files_sha256": {
        "live_result.json": "920e2c7c15c480f79076112449cada49b493198220a27b3224da9bb754f030fd",
        "checkpoints.jsonl": "7a7212e30b945d44eb11810f11b18a3d1e66424083c62e9743dd60baeda0ed37",
        "requests.jsonl": "c56d13b8d7f709d05bf3a07727a1e2d8757a3d599cbb3ba159bd353b82f2c0e0",
        "scenario_public.json": "2baaa8f47c037880a214fb7a728934034b972f061d80b0deb24101aba1cd58ba"
      }
    }
  }
]
```

Paired live rules comparison covers 6 of the six selected cases.

Paired rules runs: the canonical latency/error recovery flag was true for 5, false for 1 and null/inconclusive for 0 of 6 runs. That flag excludes shedding. The separate descriptive 30–90 s post-action windows met the full configured latency/error/shedding target in 3/6 runs; 3 failed that target and 0 were inconclusive. Meeting a post-window target alone does not establish restoration from a failing pre-window. `t_sched` defines arrival-cohort membership; in-flight pre-trigger requests can finish after an action begins, so these cohorts alone do not establish causal restoration.

- `inc-05`: canonical flag `False`; full post target `False`; rollback `True`; post shed 0/239 persisted outcomes (0.00%); successful-request p95 unavailable. Descriptive limitations: no_executed_change.
- `inc-06`: canonical flag `True`; full post target `False`; rollback `False`; post shed 230/612 persisted outcomes (37.58%); successful-request p95 6.80 s.
- `inc-15`: canonical flag `True`; full post target `False`; rollback `False`; post shed 216/249 persisted outcomes (86.75%); successful-request p95 4.77 s.

```json
[
  {
    "id": "inc-02",
    "run_directory": "runs/sd-study-r2-api2/live/inc-02-rules-20261102t074141861536z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 88.0,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 241,
        "ok": 111,
        "shed": 0,
        "failed": 130,
        "shed_rate": 0.0,
        "error_rate": 0.5394190871369294,
        "p50_latency_s": 5.789066801778972,
        "p95_latency_s": 7.0022023394703865
      },
      "after_action": {
        "requests": 2388,
        "ok": 2388,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.7048862599767745,
        "p95_latency_s": 6.461059292359278
      },
      "verification_window": {
        "requests": 255,
        "ok": 255,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 6.031878003850579,
        "p95_latency_s": 6.893637028895318
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 27.978855825960636,
    "engine_restarts": [
      {
        "knob": "gpu_memory_utilization",
        "value": 0.9,
        "status": "completed",
        "seconds": 27.978855825960636
      }
    ],
    "executed_actions": [
      {
        "action": {
          "type": "set_engine_config",
          "knob": "gpu_memory_utilization",
          "value": 0.9
        },
        "at": "2026-11-02T07:42:55.509507+00:00",
        "previous": {
          "gpu_memory_utilization": 0.61733
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-02",
      "arm": "rules",
      "run_directory": "runs/sd-study-r2-api2/live/inc-02-rules-20261102t074141861536z",
      "anchors": {
        "public_onset_s": 0.0,
        "triggering_checkpoint_s": 30.0,
        "action_completion_s": 58.0,
        "action_starts_s_approximate": [
          30.001352
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 0.0,
        "end_s": 30.0,
        "length_s": 30.0,
        "N": 134,
        "offered": 134,
        "ok": 111,
        "failed": 23,
        "shed": 0,
        "admitted": 134,
        "p95_latency_s": 7.0022023394703865,
        "error_rate": 0.17164179104477612,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 88.0,
        "end_s": 148.0,
        "length_s": 60.0,
        "N": 260,
        "offered": 260,
        "ok": 260,
        "failed": 0,
        "shed": 0,
        "admitted": 260,
        "p95_latency_s": 6.892946383822709,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": true,
        "full_configured_target_met": true,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 88.0,
        "acted_at_s": 58.0,
        "fault_window_before_action": {
          "requests": 241,
          "ok": 111,
          "shed": 0,
          "failed": 130,
          "shed_rate": 0.0,
          "error_rate": 0.5394190871369294,
          "p50_latency_s": 5.789066801778972,
          "p95_latency_s": 7.0022023394703865
        },
        "after_action": {
          "requests": 2388,
          "ok": 2388,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.7048862599767745,
          "p95_latency_s": 6.461059292359278
        },
        "post_fix_window": {
          "requests": 255,
          "ok": 255,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 6.031878003850579,
          "p95_latency_s": 6.893637028895318
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "set_engine_config",
          "status": "executed",
          "knob": "gpu_memory_utilization",
          "value": 0.9
        }
      ],
      "restarts": {
        "entries": [
          {
            "knob": "gpu_memory_utilization",
            "value": 0.9,
            "status": "completed",
            "seconds": 27.978855825960636,
            "phase": "forward"
          }
        ],
        "seconds": {
          "forward": 27.978855825960636,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": false
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "1bd8be46a074aef6b58f17d6f891ec9918ce4cd40fbe867cee616b2cb811df81",
        "checkpoints.jsonl": "cd0c024ae0c801776e97d02412506e24e32e441cdba89b451ed71e7285f2f870",
        "requests.jsonl": "4bb15b98bdc1b5b53120ce5d13e6c5c0311587011ef75a84ac2018faf19a64de",
        "scenario_public.json": "08f09589353f877448c9a026a7047c6de9cc4b73335fe82f550e83341c4991b2"
      }
    }
  },
  {
    "id": "inc-04",
    "run_directory": "runs/sd-study-r2-api2/live/inc-04-rules-20261102t074141861536z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 97.7,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 233,
        "ok": 73,
        "shed": 0,
        "failed": 160,
        "shed_rate": 0.0,
        "error_rate": 0.6866952789699571,
        "p50_latency_s": 4.831419988535345,
        "p95_latency_s": 4.955782041698694
      },
      "after_action": {
        "requests": 2308,
        "ok": 2308,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.6960635161958635,
        "p95_latency_s": 6.3817783743608745
      },
      "verification_window": {
        "requests": 218,
        "ok": 218,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.935374732129276,
        "p95_latency_s": 6.589046542765573
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 37.64894741307944,
    "engine_restarts": [
      {
        "knob": "max_model_len",
        "value": 4096,
        "status": "completed",
        "seconds": 37.64894741307944
      }
    ],
    "executed_actions": [
      {
        "action": {
          "type": "set_engine_config",
          "knob": "max_model_len",
          "value": 4096
        },
        "at": "2026-11-02T07:55:02.239802+00:00",
        "previous": {
          "max_model_len": 768
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-04",
      "arm": "rules",
      "run_directory": "runs/sd-study-r2-api2/live/inc-04-rules-20261102t074141861536z",
      "anchors": {
        "public_onset_s": 0.0,
        "triggering_checkpoint_s": 30.0,
        "action_completion_s": 67.7,
        "action_starts_s_approximate": [
          30.047124
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 0.0,
        "end_s": 30.0,
        "length_s": 30.0,
        "N": 104,
        "offered": 104,
        "ok": 71,
        "failed": 33,
        "shed": 0,
        "admitted": 104,
        "p95_latency_s": 4.954417506232858,
        "error_rate": 0.3173076923076923,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 97.7,
        "end_s": 157.7,
        "length_s": 59.999999999999986,
        "N": 235,
        "offered": 235,
        "ok": 235,
        "failed": 0,
        "shed": 0,
        "admitted": 235,
        "p95_latency_s": 6.166625524125993,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": true,
        "full_configured_target_met": true,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 97.7,
        "acted_at_s": 67.7,
        "fault_window_before_action": {
          "requests": 233,
          "ok": 73,
          "shed": 0,
          "failed": 160,
          "shed_rate": 0.0,
          "error_rate": 0.6866952789699571,
          "p50_latency_s": 4.831419988535345,
          "p95_latency_s": 4.955782041698694
        },
        "after_action": {
          "requests": 2308,
          "ok": 2308,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.6960635161958635,
          "p95_latency_s": 6.3817783743608745
        },
        "post_fix_window": {
          "requests": 218,
          "ok": 218,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.935374732129276,
          "p95_latency_s": 6.589046542765573
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "set_engine_config",
          "status": "executed",
          "knob": "max_model_len",
          "value": 4096
        }
      ],
      "restarts": {
        "entries": [
          {
            "knob": "max_model_len",
            "value": 4096,
            "status": "completed",
            "seconds": 37.64894741307944,
            "phase": "forward"
          }
        ],
        "seconds": {
          "forward": 37.64894741307944,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": false
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "48baeb135e6aacda986f41e2ab3a1ff4a3b8d0e28b0100dc9304fd45fddfa93b",
        "checkpoints.jsonl": "593455d0c58321f86c920270afcd2d3a8da581f470be5277c338f38d93cce12d",
        "requests.jsonl": "305a1c4d33bf00f6aed6569bb35c14a267a5251c36accb3152ce71c5b410481f",
        "scenario_public.json": "77bf759dd810ef824c9c8aaf20a24e148f40b86cdd9a1f080a6a443d2daa733a"
      }
    }
  },
  {
    "id": "inc-05",
    "run_directory": "runs/sd-study-r2-api2/live/inc-05-rules-20261102t074141861536z",
    "outcome": "not recovered",
    "canonical_recovered": false,
    "rolled_back": true,
    "canonical": {
      "recovered": false,
      "time_to_recover_s": null,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 120,
        "ok": 120,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 24.797542091924697,
        "p95_latency_s": 46.79614506228827
      },
      "after_action": {
        "requests": 2514,
        "ok": 28,
        "shed": 0,
        "failed": 2486,
        "shed_rate": 0.0,
        "error_rate": 0.9888623707239459,
        "p50_latency_s": 53.95471498463303,
        "p95_latency_s": 59.72460849876516
      },
      "verification_window": {
        "requests": 246,
        "ok": 0,
        "shed": 0,
        "failed": 246,
        "shed_rate": 0.0,
        "error_rate": 1.0,
        "p50_latency_s": null,
        "p95_latency_s": null
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 0,
    "engine_restarts": [],
    "executed_actions": [
      {
        "action": {
          "type": "escalate_to_human"
        },
        "at": "2026-11-02T08:07:07.495659+00:00",
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-05",
      "arm": "rules",
      "run_directory": "runs/sd-study-r2-api2/live/inc-05-rules-20261102t074141861536z",
      "anchors": {
        "public_onset_s": 0.0,
        "triggering_checkpoint_s": 30.0,
        "action_completion_s": 30.0,
        "action_starts_s_approximate": [
          30.00305
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 0.0,
        "end_s": 30.0,
        "length_s": 30.0,
        "N": 120,
        "offered": 120,
        "ok": 120,
        "failed": 0,
        "shed": 0,
        "admitted": 120,
        "p95_latency_s": 46.79614506228827,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 60.0,
        "end_s": 120.0,
        "length_s": 60.0,
        "N": 239,
        "offered": 239,
        "ok": 0,
        "failed": 239,
        "shed": 0,
        "admitted": 239,
        "p95_latency_s": null,
        "error_rate": 1.0,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": false,
        "rolled_back": true,
        "time_to_recover_s": null,
        "acted_at_s": 30.0,
        "fault_window_before_action": {
          "requests": 120,
          "ok": 120,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 24.797542091924697,
          "p95_latency_s": 46.79614506228827
        },
        "after_action": {
          "requests": 2514,
          "ok": 28,
          "shed": 0,
          "failed": 2486,
          "shed_rate": 0.0,
          "error_rate": 0.9888623707239459,
          "p50_latency_s": 53.95471498463303,
          "p95_latency_s": 59.72460849876516
        },
        "post_fix_window": {
          "requests": 246,
          "ok": 0,
          "shed": 0,
          "failed": 246,
          "shed_rate": 0.0,
          "error_rate": 1.0,
          "p50_latency_s": null,
          "p95_latency_s": null
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "escalate_to_human",
          "status": "executed"
        }
      ],
      "restarts": {
        "entries": [],
        "seconds": {
          "forward": 0.0,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": true,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": false
      },
      "inconclusive": true,
      "interpretation": "Inconclusive descriptive restoration comparison; see flags and unchanged canonical outcomes.",
      "public_files_sha256": {
        "live_result.json": "5289fceebe473807694f86fbc2480098cbd3b939359ae0b89fdb55887ee6297e",
        "checkpoints.jsonl": "167650d6ceac8c6eea5cde2fdd9a16193e3a715fe60f5ffb23f1f6290d48f800",
        "requests.jsonl": "63d43fd2b2e40b2198193097a4dca2762803312c357914cc21dc49532ebda486",
        "scenario_public.json": "47a5595c3faa76fd1791d6d7cc4fc8140a5f6758c11241219cfead6d8b0f5cd3"
      }
    }
  },
  {
    "id": "inc-06",
    "run_directory": "runs/sd-study-r2-api2/live/inc-06-rules-20261102t074141861536z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 80.0,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 303,
        "ok": 303,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 10.400326213799417,
        "p95_latency_s": 13.991015902534127
      },
      "after_action": {
        "requests": 5290,
        "ok": 3265,
        "shed": 2025,
        "failed": 0,
        "shed_rate": 0.3827977315689981,
        "error_rate": 0.0,
        "p50_latency_s": 6.365689636208117,
        "p95_latency_s": 9.135413839481766
      },
      "verification_window": {
        "requests": 604,
        "ok": 386,
        "shed": 218,
        "failed": 0,
        "shed_rate": 0.3609271523178808,
        "error_rate": 0.0,
        "p50_latency_s": 6.3630047757178545,
        "p95_latency_s": 7.6168604826088995
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 0,
    "engine_restarts": [],
    "executed_actions": [
      {
        "action": {
          "type": "gateway_rate_limit",
          "max_rps": 6.4
        },
        "at": "2026-11-02T08:22:07.059253+00:00",
        "previous": {
          "max_rps": null,
          "max_prompt_tokens": null
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-06",
      "arm": "rules",
      "run_directory": "runs/sd-study-r2-api2/live/inc-06-rules-20261102t074141861536z",
      "anchors": {
        "public_onset_s": 120.0,
        "triggering_checkpoint_s": 150.0,
        "action_completion_s": 150.0,
        "action_starts_s_approximate": [
          150.005107
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 120.0,
        "end_s": 150.0,
        "length_s": 30.0,
        "N": 303,
        "offered": 303,
        "ok": 303,
        "failed": 0,
        "shed": 0,
        "admitted": 303,
        "p95_latency_s": 13.991015902534127,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 180.0,
        "end_s": 240.0,
        "length_s": 60.0,
        "N": 612,
        "offered": 612,
        "ok": 382,
        "failed": 0,
        "shed": 230,
        "admitted": 382,
        "p95_latency_s": 6.796076009282842,
        "error_rate": 0.0,
        "shed_rate": 0.3758169934640523,
        "latency_error_target_met": true,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 80.0,
        "acted_at_s": 150.0,
        "fault_window_before_action": {
          "requests": 303,
          "ok": 303,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 10.400326213799417,
          "p95_latency_s": 13.991015902534127
        },
        "after_action": {
          "requests": 5290,
          "ok": 3265,
          "shed": 2025,
          "failed": 0,
          "shed_rate": 0.3827977315689981,
          "error_rate": 0.0,
          "p50_latency_s": 6.365689636208117,
          "p95_latency_s": 9.135413839481766
        },
        "post_fix_window": {
          "requests": 604,
          "ok": 386,
          "shed": 218,
          "failed": 0,
          "shed_rate": 0.3609271523178808,
          "error_rate": 0.0,
          "p50_latency_s": 6.3630047757178545,
          "p95_latency_s": 7.6168604826088995
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "gateway_rate_limit",
          "status": "executed",
          "max_rps": 6.4
        }
      ],
      "restarts": {
        "entries": [],
        "seconds": {
          "forward": 0.0,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": true
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "8f44d0c25dfe780bd9085fd70d4dba502f7006287c8ccd89edc8dce7ba0a73e7",
        "checkpoints.jsonl": "70b7119b5d90435d82563565e95b48d94bbfd7245a877eee7b4cf00aafef0c2a",
        "requests.jsonl": "e929261cf4980c95022388f5391a3d5124f3a528ae7a23209cdf8265611946a1",
        "scenario_public.json": "15dec2dd00efb8508b38cce458ecd3bc3308a709a9cd5e36e5d414b58ce5e243"
      }
    }
  },
  {
    "id": "inc-09",
    "run_directory": "runs/sd-study-r2-api2/live/inc-09-rules-20261102t074141861536z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 60.2,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 129,
        "ok": 129,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 11.586972513236105,
        "p95_latency_s": 13.276523720286786
      },
      "after_action": {
        "requests": 2058,
        "ok": 2058,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.682574088219553,
        "p95_latency_s": 6.54696047976613
      },
      "verification_window": {
        "requests": 234,
        "ok": 234,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 5.6793491104617715,
        "p95_latency_s": 6.273840054729954
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 0,
    "engine_restarts": [],
    "executed_actions": [
      {
        "action": {
          "type": "stop_gpu_process",
          "pid": 34197
        },
        "at": "2026-11-02T08:34:14.143813+00:00",
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-09",
      "arm": "rules",
      "run_directory": "runs/sd-study-r2-api2/live/inc-09-rules-20261102t074141861536z",
      "anchors": {
        "public_onset_s": 120.0,
        "triggering_checkpoint_s": 150.0,
        "action_completion_s": 150.2,
        "action_starts_s_approximate": [
          150.006624
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 120.0,
        "end_s": 150.0,
        "length_s": 30.0,
        "N": 129,
        "offered": 129,
        "ok": 129,
        "failed": 0,
        "shed": 0,
        "admitted": 129,
        "p95_latency_s": 13.276523720286786,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 180.2,
        "end_s": 240.2,
        "length_s": 60.0,
        "N": 244,
        "offered": 244,
        "ok": 244,
        "failed": 0,
        "shed": 0,
        "admitted": 244,
        "p95_latency_s": 6.76499657263048,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": true,
        "full_configured_target_met": true,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 60.2,
        "acted_at_s": 150.2,
        "fault_window_before_action": {
          "requests": 129,
          "ok": 129,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 11.586972513236105,
          "p95_latency_s": 13.276523720286786
        },
        "after_action": {
          "requests": 2058,
          "ok": 2058,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.682574088219553,
          "p95_latency_s": 6.54696047976613
        },
        "post_fix_window": {
          "requests": 234,
          "ok": 234,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 5.6793491104617715,
          "p95_latency_s": 6.273840054729954
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "stop_gpu_process",
          "status": "executed",
          "pid": 34197
        }
      ],
      "restarts": {
        "entries": [],
        "seconds": {
          "forward": 0.0,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": false
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "f03b5f4c424121ea673c7d5c208359649c64afa406cdfffc25336dee883693c4",
        "checkpoints.jsonl": "eea5795756154451ce813d6378aeb60925f9ffc65fc47cdf623ca5b49155f0bb",
        "requests.jsonl": "9bcabbe7fdbd1427ae6f7ff1cfac1b9e8364f8d617264e9b0411068dbf5cba4b",
        "scenario_public.json": "87824d5679e04dfa33a332a23610b21fef5341bedf6a1d3148f5eeed48749184"
      }
    }
  },
  {
    "id": "inc-15",
    "run_directory": "runs/sd-study-r2-api2/live/inc-15-rules-20261102t074141861536z",
    "outcome": "recovered",
    "canonical_recovered": true,
    "rolled_back": false,
    "canonical": {
      "recovered": true,
      "time_to_recover_s": 80.0,
      "time_origin": "fault onset",
      "fault_window_before_action": {
        "requests": 118,
        "ok": 118,
        "shed": 0,
        "failed": 0,
        "shed_rate": 0.0,
        "error_rate": 0.0,
        "p50_latency_s": 36.09199000056833,
        "p95_latency_s": 41.61463701110333
      },
      "after_action": {
        "requests": 2030,
        "ok": 329,
        "shed": 1701,
        "failed": 0,
        "shed_rate": 0.8379310344827586,
        "error_rate": 0.0,
        "p50_latency_s": 4.7377025950700045,
        "p95_latency_s": 4.8052569216117265
      },
      "verification_window": {
        "requests": 262,
        "ok": 40,
        "shed": 222,
        "failed": 0,
        "shed_rate": 0.8473282442748091,
        "error_rate": 0.0,
        "p50_latency_s": 4.7310751234181225,
        "p95_latency_s": 4.757336535165086
      },
      "recovered_checks_shed_cap": false
    },
    "engine_restart_seconds": 0,
    "engine_restarts": [],
    "executed_actions": [
      {
        "action": {
          "type": "gateway_max_prompt_tokens",
          "max_prompt_tokens": 404
        },
        "at": "2026-11-02T08:46:17.299404+00:00",
        "previous": {
          "max_rps": null,
          "max_prompt_tokens": null
        },
        "status": "executed"
      }
    ],
    "cleanup_errors": [],
    "descriptive_window_audit": {
      "id": "inc-15",
      "arm": "rules",
      "run_directory": "runs/sd-study-r2-api2/live/inc-15-rules-20261102t074141861536z",
      "anchors": {
        "public_onset_s": 120.0,
        "triggering_checkpoint_s": 150.0,
        "action_completion_s": 150.0,
        "action_starts_s_approximate": [
          150.004012
        ],
        "action_start_basis": "executed.at minus scenario_public.started_at; t0 offset is not persisted"
      },
      "slo": {
        "p95_latency_s": 10.0,
        "max_error_rate": 0.01,
        "max_shed_rate": 0.05
      },
      "pre": {
        "start_s": 120.0,
        "end_s": 150.0,
        "length_s": 30.0,
        "N": 118,
        "offered": 118,
        "ok": 118,
        "failed": 0,
        "shed": 0,
        "admitted": 118,
        "p95_latency_s": 41.61463701110333,
        "error_rate": 0.0,
        "shed_rate": 0.0,
        "latency_error_target_met": false,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "post": {
        "start_s": 180.0,
        "end_s": 240.0,
        "length_s": 60.0,
        "N": 249,
        "offered": 249,
        "ok": 33,
        "failed": 0,
        "shed": 216,
        "admitted": 33,
        "p95_latency_s": 4.768970550596714,
        "error_rate": 0.0,
        "shed_rate": 0.8674698795180723,
        "latency_error_target_met": true,
        "full_configured_target_met": false,
        "count_basis": "persisted request outcomes by scheduled arrival; no missing arrivals inferred"
      },
      "canonical": {
        "recovered": true,
        "rolled_back": false,
        "time_to_recover_s": 80.0,
        "acted_at_s": 150.0,
        "fault_window_before_action": {
          "requests": 118,
          "ok": 118,
          "shed": 0,
          "failed": 0,
          "shed_rate": 0.0,
          "error_rate": 0.0,
          "p50_latency_s": 36.09199000056833,
          "p95_latency_s": 41.61463701110333
        },
        "after_action": {
          "requests": 2030,
          "ok": 329,
          "shed": 1701,
          "failed": 0,
          "shed_rate": 0.8379310344827586,
          "error_rate": 0.0,
          "p50_latency_s": 4.7377025950700045,
          "p95_latency_s": 4.8052569216117265
        },
        "post_fix_window": {
          "requests": 262,
          "ok": 40,
          "shed": 222,
          "failed": 0,
          "shed_rate": 0.8473282442748091,
          "error_rate": 0.0,
          "p50_latency_s": 4.7310751234181225,
          "p95_latency_s": 4.757336535165086
        },
        "failure": null,
        "failure_stage": null,
        "cleanup_errors": []
      },
      "executed": [
        {
          "type": "gateway_max_prompt_tokens",
          "status": "executed",
          "max_prompt_tokens": 404
        }
      ],
      "restarts": {
        "entries": [],
        "seconds": {
          "forward": 0.0,
          "rollback": 0.0,
          "unclassified": 0.0
        }
      },
      "error_classes": {
        "runtime": [],
        "calls": [],
        "actions": []
      },
      "flags": {
        "trigger_pre_onset": false,
        "action_start_pre_onset_approximate": false,
        "action_completion_pre_onset": false,
        "no_executed_change": false,
        "canonical_verification_missing": false,
        "partial_jsonl": false,
        "both_latency_error_windows_met": false,
        "post_shedding_exceeds_configured_cap": true
      },
      "inconclusive": false,
      "interpretation": "Latency/error target attained in the post window after a pre-window miss; temporal association only, not causal proof.",
      "public_files_sha256": {
        "live_result.json": "27fecf8619002a93472a77593373b554a6ab0d562a5c6d9d5d83c304294a7a54",
        "checkpoints.jsonl": "3a8a2e9f5580945b9d131d516fe318b0b6c426d81a5e59681bc4504798593050",
        "requests.jsonl": "9aba8e31d73f44f02123e1675380bd86551192f8e02ca915b0e628146c1cdb7b",
        "scenario_public.json": "9e002d7dd1ee67582ea8a6e224195368a2c5c03790d7cdb5ecca5fcb8df3200b"
      }
    }
  }
]
```

Completed unrecovered or rolled-back runs are measured outcomes. A missing recovery verification window is reported as inconclusive. Runtime exceptions and paid call rejections remain failed attempts and are not retried invisibly.

## Spend and validation

```json
{
  "caps_usd": {
    "meta": 50.0,
    "baseten": 20.0
  },
  "accounted_usd": {
    "meta": 12.255891,
    "baseten": 0.0
  },
  "warnings": [],
  "calls": 443
}
```

Accounted totals include retained failed-call reservations; settled token-usage cost and conservative reservations are distinct.

```json
{
  "running_hours": 14.302194860312673,
  "compute_usd_upper": 20.260777200619028,
  "disk_usd_upper": 0.63932723481622,
  "rental_usd_upper": 20.90010443543525,
  "network_allowance_usd": 4.0,
  "slack_reserve_usd": 1.0,
  "total_usd_upper": 25.90010443543525
}
```

Final observed stop: `2026-11-02T09:12:35.273595+00:00`. Scoped deletion is confirmed; the aggregate retained-disk estimate is fixed.

GPU accounting charges startup and shutdown uncertainty conservatively and retained disk during stops. A stale stopped observation briefly closed one active interval after 0.48 seconds. Accounting was corrected to charge the entire session from its original start; the invalid observation was retained. Interval-specific readiness and stop checks fixed the watcher race. Benchmark data and the API ledger were unchanged.

The original rental finalized at 2.848502 running hours and a $3.952246 rental estimate. Final totals include both sequential rentals, $4 combined transfer allowance, $1 slack and any retained disk. The user explicitly authorized keeping the replacement allocated through troubleshooting and stage gaps, accepting approximately $2–3 extra holding cost. The $40 aggregate cap and November 2 noon Eastern fallback remained in force. Final deletion uses the exact immutable replacement scope, after the complete study and canonical ledger are backed up; an unknown DELETE outcome permits read-only reconciliation only.

```json
{
  "command": "python3 -m unittest discover -s tests -q",
  "ran": 289,
  "skipped": 1,
  "passed": true,
  "duration_s": 45.681,
  "source_commit": "a0b4deb6e9545b9d21fde472ad4686645b083bc6",
  "output": "runs/servedoctor-ops-20261101/unittest-20261102T0146.stdout",
  "separately_prepared_post_study_fix": {
    "commit": "da5596d9595214bd912bf15788d82cf58f5547ea",
    "ran": 302,
    "skipped": 1,
    "passed": true,
    "used_for_frozen_measurements": false,
    "evidence": "runs/servedoctor-ops-20261101/collector-fix-prepared-da5596d.json"
  }
}
```

```json
{
  "gpu_instance_id": 58716527,
  "observed_stopped_at_utc": "2026-11-02T09:12:35.273595+00:00",
  "instance_status": {
    "actual_status": "exited",
    "cur_state": "stopped",
    "intended_status": "stopped"
  },
  "all_gpu_work_stopped": true,
  "remote_guards_stopped": true,
  "no_pending_paid_calls": true,
  "canonical_ledger_sha256": "13f777ed328bb0c71bb2063b6b12cf3b6cb8024d78b0ab46b9e374521a566123",
  "gpu_hours_log_sha256": "baf129ad0a06ea19ca7c921aafd42eb2fb0fa17a2201b4320dde054ac94263f8",
  "destroy_receipt": {
    "path": "/Users/rajoza/Documents/ChatGPT/meta hackathon/servetune/runs/servedoctor-ops-20261101/destroy-receipt-58716527.json",
    "sha256": "9c28a7d7b972a89cc9e25f079db45310066afacd4e7d3bd300c4ed87894483de"
  }
}
```

Before r2 generation, `python3 -m unittest discover -s tests -q` passed 283 tests in 45.011 seconds, with one skip. The output remains in `provenance/operations/unittest-20261101T2252.stdout`. An earlier 278-test run failed on the context-fault fixture race; its failure record is retained separately. The final validation and cleanup evidence are recorded below.

The final transport source at `a0b4deb6e9545b9d21fde472ad4686645b083bc6` passed 289 tests in 45.681 seconds, with one skip, before the API2 attempt. The output remains in `provenance/operations/unittest-20261102T0146.stdout`.

## Failures and retained evidence

- SSH access required the official key attachment, and strict known-hosts validation plus an option path needed correction. The corrected attempts remain separately documented.
- The first GPU calibration loaded weights but failed tokenizer startup after worker revisions rendered as `main`. That directory remains in `provenance/calibration-failed-attempt1/`; the successful second attempt used the pinned offline snapshot.
- An unavailable tokenize endpoint returned `URLError`. A subsequent tokenizer measurement incorrectly counted two mapping fields instead of `input_ids`; it is explicitly labeled invalid. Both failed measurements remain, alongside the corrected count.
- The initial KV study had an ineffective development fault and remains labeled as superseded development evidence. The final study uses the separately recorded refined severity configuration.
- GPU startup accounting and watcher corrections are recorded above; no paid ledger was reset or edited.
- The first paid development attempt recorded 192 failed checkpoints with `UnicodeEncodeError` and no successful API usage responses. The ledger retained $9.075474 in conservative reservations; this is not a claim of billed API spend. The complete failed `runs/sd-study-kv2` remains in `provenance/failed-api-development-study/`. A fresh `runs/sd-study-kv2-api2` reused the sealed recordings and unchanged rules decisions without transferring failed model decisions. A new minimum checkpoint requires a successful usage-bearing Spark response for every dev incident and zero recorded call failures.
- The first attempt's minimum-checkpoint marker was invalid and is retained as historical failed evidence. The minimum checkpoint was not met by that attempt. An operator tail-argument signal also interrupted its outer phase wrapper; the stage copied its evidence without cleanup errors, and the operator explicitly stopped the rental and confirmed actual `exited` / current `stopped` state. Future wrappers forward termination to the evaluation child and allow bounded cleanup before stopping the instance.
- The original host could not restart. Its migration backup preserves nine sealed reference/development recordings and 63 sealed data files across the retained study copies, plus failed calls and ledger reservations. A successful SCP transfer and controller no-later-dispatch attestation establish the last ledger copy; no independent remote ledger digest was captured before retirement. The migration receipt states that limit and does not claim a final copy of every late operational log. This historical exception is separate from the final replacement backup, which requires an observed remote ledger digest.
- Two replacement creation requests were rejected without creating an instance. Their preserved markers and inventory reconciliation precede the single successful creation. Only one GPU rental was held at a time.
- Replacement bootstrap attempt 1 stopped during the public model download after guard upload failed because its destination directory did not exist. Attempt 2 stopped when the guard did not recognize the trusted temporary bootstrap process. Both partial output directories and safe controller outcomes are retained. Attempt 3 completed with pinned offline weights. Guard arming now creates its destination and verifies the exact temporary bootstrap source before recognizing that process.
- Original replacement study r2 retained one failed Wonder HTTP404 checkpoint and its conservative reservation. Its completed recordings and decisions remain separate history. API2 retains explicit copy lineage and transport proofs; no failed checkpoint was erased or silently retried.

Replacement KV attempt 1 remains preserved in `provenance/kv-pre-generation-attempt1/`; its interrupted summary still reports `running` and records no completed candidate summaries, so it is not counted as successful calibration. Attempt 2 completed separately in `provenance/kv-pre-generation-attempt2/` and supplies the selected measurements above.

- The original paid development attempt retained192 UnicodeEncodeError failures and$9.075474 conservative reservations, with zero successful token-usage responses. They are not claimed as billed completions. The ledger was never reset, edited or released.
- The original rental was stopped under the initial idle policy and could not restart because its resources were unavailable. The user approved replacement and a complete hardware rerun, then required holding the replacement through stage gaps. Original migration evidence candidly lacks an independently observed remote ledger digest; the final replacement mirror has an independently captured remote digest.
- Replacement bootstrap attempts 1 and 2 retained guard/upload/process-recognition integration failures during public model download; attempt 3 succeeded. Calibration/KV summary-writer failures and all superseded dev studies remain separately labeled provenance. Only development data and pre-generation probes informed severities and the one rule-threshold change.
- Test batch 1 lost its local controller after a heartbeat lock wait, while the remote recorder sealed incidents 01 and 06. The recorder then hit BrokenPipeError while printing; original CLI exit is unknown. A durable continuation recorded only the six previously unstarted IDs. Original failed controller/recorder evidence and reconciliation receipts remain.
- Original test incident 23 hit the 1,024 soft file-descriptor limit and stopped telemetry early, although the old harness falsely marked completion. Before any test model evaluation, one fresh same-workload recording raised only its worker/engine soft limit to 65,536, retained the original failure byte-for-byte, and explicitly adopted the complete 4,667-outcome replacement. All 25 recordings and 175 sealed payload hashes passed structural checks; the other 24 manifests were unchanged.
- The collector failure-propagation fix da5596d9595214bd912bf15788d82cf58f5547ea was prepared and independently tested separately, 302 tests with 1 skip. It was not used for any frozen GPU measurement, and all frozen-source backup/package gates ran on a0b4deb. The earlier d2632e4 candidate had a late-writer race and remains labeled superseded.
- The original replacement Wonder call returned HTTP 404, retained its partial and$0.063304 reservation, and halted. Catalog visibility changed; the evidence does not establish why 404 occurred. API2 copied nine sealed recordings and 24 successful rules/Spark/Glimmer dev decisions on the same replacement GPU, kept the canonical ledger, and used an explicit Mac-origin HTTPS CONNECT route with end-to-end TLS, unchanged model IDs/prices/prompts and no relay payload logging.
- Wonder produced one genuine invalid JSON response on the test split. It remains in the checkpoint journal and API accounting. There were no paid call failures in the completed final dev/test evaluation arms.
- The context-fault live cascade retained a local monitor HTTPError under the restricted context and escalated to Spark under the already frozen fallback. Monitor availability and serving failures during engine restarts are retained, including connection and request errors.
- Both live arms had canonical recovery true in 5 of 6 cases. The cascade failed and rolled back the long-prompt case, which had 813 successes, 1,244 timeouts and 548 shed requests. Rules classified the batch case as other and requested advisory human escalation; it applied no service change, had 148 successes and 2486 timeouts, and its canonical rollback flag is bookkeeping rather than an actual undo.
- Canonical recovery excludes the configured 5% shed cap. The cascade surge post cohort shed 361 of 601 requests (60.07%), and the rules surge post cohort shed 37.58%. Long-prompt post shedding was 83.77% for the cascade and 86.75% for rules. Full latency/error/shedding post targets were met in 4 of 6 cascade cases and 3 of 6 rules cases.
- Pre and post descriptive windows were declared before test evaluation and live outcomes. Membership uses scheduled arrival t_sched; pre-trigger requests can complete during intervention/restart, so their later errors are not a clean completed-before-intervention baseline. Canonical verification uses a distinct lagged online window and onset-relative recovery time. Matched cases are separate temporal runs; these cohorts and six cases do not establish causal or general superiority.
- A premature final audit ran before the full copy completed and correctly rejected missing rules traces. Its two outputs are preserved in final-audit-attempt1-premature-mirror. Fresh audits in a new directory ran only after the verified full mirror, and passing bytes were adopted with an explicit receipt. No recording or model call was repeated.
- The full per-file SCP copy timed out after 180 seconds. A single archive transfer succeeded, then local extraction hit an unsupported Python tarfile filter keyword. Both failures are retained. Fresh validated file-by-file extraction from that same archive produced all 543 files (51,088,775 bytes), matching independent before/after remote hashes and the canonical ledger digest. No scientific input or measurement was changed.
- An early operational note incorrectly counted 201 frozen entries; the actual 169-entry freeze and its hash never changed. The bookkeeping correction is preserved. An earlier offline context-fixture timing failure and the superseded collector-fix candidate remain in provenance.
- The study covers one verified replacement GPU, one pinned engine build and one model revision. The rules were written by fault designers and tuned on dev, making them an optimistic baseline. No statistical-significance or generalization claim is made. API token costs use conservative standard rates without cached-input discounts; retained failed reservations and settled usage are distinct from provider invoices. GPU network and slack amounts are reserves.

Test batch 1's local controller timed out while renewing its heartbeat lock and retained an interrupted/forced-termination outcome. The original remote recorder initially continued independently. Its early controller outcome is not evidence that all eight recordings completed. The interruption receipt, original phase exit and safe phase log remain preserved; actual seals and the separate continuation reconciliation establish completion while the original interruption and unknown original recorder exit remain retained. The later all 25 quality audit also includes the explicit incident 23 repair.

The continuation added one base-engine start before `inc-09`. Measurement knobs, seeds, request windows and recording durations were unchanged, and no completed recording was re-recorded. The separate process-observation correction distinguishes the earlier liveness query from the interruption receipt creation time; receipt creation alone is not a fresh liveness probe.

Incident `inc-23` exposed a collection failure: its original sampler stopped at second 231 of a 360-second workload after `OSError` / `EMFILE`, while the frozen recorder incorrectly wrote `completed`. The repair protocol requires the original 232 telemetry rows and raw status to remain unchanged, with an external unusable label in `recording-failures/inc-23-emfile-attempt1/`; it retains the original batch outcome separately before adoption. A new-directory resource-limit repair attempt uses the same frozen scenario, seed, arrivals and measurement windows. It raises only inherited `RLIMIT_NOFILE` soft headroom from 1,024 to 65,536 before the recorder and engine start; the hard limit remains 1,048,576. Parent/child limit proofs and a separate adoption receipt bind the retained original and replacement bytes. Final usability requires all 25 reference/dev/test recordings to pass independent seal, telemetry-coverage and exact request-ID/time/class completeness checks; no latency, fault-severity or model-performance criterion selects the replacement. The scratch run remains in `provenance/incident23-fd-repair-attempt1/`, and before/after collection-quality reports remain in `provenance/operations/`.

The explicit adoption completed at `2026-11-02T04:58:01.632585Z`, before test model decisions, after all 25 canonical recordings passed structural completeness and all 24 other manifest hashes remained unchanged. `test-recording-batch-receipts/inc-23-fd-repair-adoption.json` binds original, replacement, limits and before/after quality evidence. The historical collector log still carries its EMFILE review flag; a separate resolution explains why its isolated raw episode is excluded from active recordings, rather than erasing that failure.

Collector fix `da5596d9595214bd912bf15788d82cf58f5547ea` was prepared and tested separately in an isolated worktree after this failure was observed. Its 302-test offline suite passed with one skip. It captures safe background failure classes, propagates failed dispatch, retains failed partial recording artifacts and preserves the primary exception during cleanup. If a collector remains alive after its bounded stop, the failed recording stays explicitly unsealed because telemetry may still change; quiescent failed recordings retain their seals. Late-release regressions cover that distinction and the live caller. This patch was not used for frozen measurements. Its preparation descriptor and test output are preserved separately; preparation did not apply it to the experiment branch. The earlier `d2632e4` draft and 300-test output remain retained as superseded: independent review reproduced a late writer changing an already sealed file. Any later publication application is distinct from frozen experiment source `a0b4deb`.

Finalization preserved two procedural failures: the first audits ran before the full SCP mirror finished, so their incomplete outputs remain separately labeled; the first SCP transfer then timed out. The compressed transport succeeded but its local extraction hit an unsupported Python filter keyword, which is retained as a separate failure. Fresh validated extraction completed, all 543 files  / 51,088,775 bytes matched two remote snapshots and the canonical ledger hash, and fresh 12-run audits passed before exact report-byte adoption. No recording or model call was repeated, and the window definitions, metric calculations and scoring rules remained unchanged.

## Package layout and limits

The root contains the final replacement study, opaque sealed answers, decisions, live recordings, reports, freeze and selection records, final ledger evidence and aggregate GPU accounting. `provenance/` retains selected replacement and original calibrations, both replacement KV attempts, partial bootstrap outputs, change evidence, original studies and the explicit migration/retirement proof. Historical migration manifests contain local backup descriptors; their private session snapshots stay outside the public package. `package-manifest.json` records hashes of all copied files. Existing incident manifests are preserved.

Durable recorder receipts keep their original remote OPS references. The seven public files for each reviewed durable attempt—dispatch, launch, worker stdout/stderr, recorder stdout/stderr and exit—are mirrored under `provenance/operations/durable-test-recordings/<attempt>/` when actually present. Private controller/staged trees are excluded. Missing exit or reconciliation evidence is not interpreted as successful completion.

Model weights, caches, credentials, SSH material, private operational sessions and key workers are excluded. ServeTune v4 sources and `results/20261030/` remain unchanged.

The rules were written by the fault designers and tuned on development data, so they are an optimistic baseline. The comparison is limited to this frozen incident set and serving environment. No statistical significance or generalization claim is made.

No further user decision is recorded in the final report.
