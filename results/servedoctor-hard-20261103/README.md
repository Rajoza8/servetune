# ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)


This is the explicitly approved analysis of the fifteen completed incidents from the original sixteen-incident Hard specification. One reference and `hard-01` through `hard-15` were recorded. `hard-16` could not start; the original attempt remains preserved and is not represented as a full sixteen-case result. The exclusion was recorded at `2026-11-02T23:07:44.538859+00:00`, before any native Hard validation or model-arm evaluation. Native prompts, rules, thresholds, answer keys and scoring did not change.

The failed engine used frozen KV utilization `0.61632` with a generated `max_num_batched_tokens=12288`, whereas the standalone pre-generation calibration used 8192. vLLM reported **-0.54 GiB** available KV cache; cleanup left 2 MiB and no compute process. The incident was not retuned, regenerated or re-recorded. The original 16 key/scenario bytes, freeze and failed startup are retained under `original-frozen-attempt/`.

The measurements were made on recording instance `58866756`, physical GPU `GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681`. Before generation, that host was calibrated to 6 RPS; the unchanged mild/compound standalone KV values 0.61632/0.61520 gave p95 10.004323831864165s/15.239633663152924s, with 268/268 requests successful in each. The original host was later unavailable for a queued restart and was retired after its available local scientific evidence was backed up. Its later remote OPS/control tail was explicitly unverified.

Inference runs separately on verified Texas instance `58905385`, scope `7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7`. Actual inference GPU UUID: **GPU-a38fda97-350c-5724-46e6-82b87f985a96**; driver/vLLM: **610.43.02 / 0.26.1rc1.dev608+g99a10304d**. No new generation, calibration, benchmark recording or scientific configuration change occurred on this inference host. Both hosts use the pinned RTX PRO 6000 Blackwell 96 GB environment, BF16 Glimmer 30B revision `cec94fcfd6512f2cfe708138c32533b346ea4f69`; exact hardware/runtime proofs accompany the package.

| Frozen item | Value |
| --- | --- |
| Recording/evaluation source | `4b0add12be36cef0d0776607f683310b1641b0f7` |
| Original config SHA256 | `0cc70e7ec4cbb0b26c6e13a4b9311dedf6dd05a862d9c0d9d2934ec25a017014` |
| Original 16 answer commitment | `fb168177884005df77a94cbb75e6d52946a26ccfc3675db82820bb9105eaadc0` |
| Original 16 scenario commitment | `bbd1f792878602f6472e56a5795f9f257882ad541b3184ce38af00588c4d3f20` |
| Original 16 freeze SHA256 | `868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68` |
| Pre-validation exclusion SHA256 | `783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9` |
| Dated GPU budget amendment SHA256 | `8efba5368ca146e45ff55d16fb45567058ae015bcee51a26a5510a0e31c4ee2a` |
| New operator inference protocol SHA256 | `c5750faf63511320424d40791f645ffc891f4d1cb814315d5aab0b6b3fd24cef` |

Two historical ancillary raw JSON files remain unavailable: `preflight-readiness.json` (`142e8954…`) and its declaration JSON (`8b5534f7…`). Their commitments, successful readiness stdout and the failed stopped-host recovery attempt remain recorded. The original 178 files, sixteen recording manifests, 112 sealed payload files and owned-observer proofs were verified separately. The portable operator gate explicitly discloses the two gaps and **does not claim the old full verify_freeze gate passed**. Original descriptors and freeze bytes were not rewritten to conceal missing evidence.

The original three API transport files were bound to the recording host. Only the analysis copy archives those exact bytes at `operator-provenance/original-api-transport/`, then freezes a new-instance transport trio. Spark and Wonder use a TLS-blind Mac CONNECT relay to the fixed official `api.meta.ai:443` endpoint. The relay sees no Bearer credential or model body; the diagnostic GET uses the same verified native CONNECT transport as paid calls. Model IDs, per-token rates, native messages and payload parameters are unchanged. Spark is `muse-spark-1.3` at $1.25 input/$4.25 output per million tokens; Wonder is `muse-wonder-1.0` at $4/$20. [Official model IDs](https://dev.meta.ai/docs/models) and [standard pricing](https://dev.meta.ai/docs/pricing-rate-limits) were rechecked before inference; the exact receipt is preserved.

**Actual validity:** 14 valid and 1 invalid, out of 15 retained cases. The unchanged native rule was run once before arm evaluation. Invalid symptoms remain in the all 15 scoreboard, and valid-only uses the same decisions. **Actual coverage:** 90 of 90 decisions: all six arms across the fifteen retained incidents. Failed calls remain recorded canonical failures; invalid JSON remains an invalid model result. No model output was silently retried or dropped.

All 15 scoreboard (`python3 -m servedoctor score --study-dir runs/sd-hard-partial-attempt1 --split hard`):

| Arm | Detected | False alarms | Diagnosis correct | Fix proposed | Complete fix | Compound complete fix | Harmful | Decoy stops | Invalid JSON | Failed calls | Median detection s | Model calls | API USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rules | 11 | 2 | 7 | 6 | 3 | 0 | 5 | 5 | 0 | 0 | 30 | 0 | 0.0 |
| glimmer | 11 | 0 | 11 | 11 | 7 | 0 | 0 | 0 | 0 | 0 | 30 | 0 | 0.0 |
| spark | 11 | 0 | 11 | 11 | 7 | 0 | 0 | 0 | 0 | 0 | 30 | 88 | 0.5435 |
| wonder | 12 | 0 | 10 | 10 | 6 | 0 | 0 | 0 | 1 | 0 | 30 | 77 | 1.6443 |
| glimmer_to_spark | 10 | 0 | 8 | 8 | 4 | 0 | 0 | 0 | 0 | 0 | 30 | 10 | 0.0773 |
| glimmer_to_wonder | 10 | 0 | 9 | 9 | 5 | 0 | 0 | 0 | 5 | 0 | 30 | 15 | 0.5847 |

Valid-only scoreboard (same command with `--valid-only`):

| Arm | Detected | False alarms | Diagnosis correct | Fix proposed | Complete fix | Compound complete fix | Harmful | Decoy stops | Invalid JSON | Failed calls | Median detection s | Model calls | API USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rules | 10 | 2 | 7 | 6 | 3 | 0 | 5 | 5 | 0 | 0 | 30 | 0 | 0.0 |
| glimmer | 11 | 0 | 11 | 11 | 7 | 0 | 0 | 0 | 0 | 0 | 30 | 0 | 0.0 |
| spark | 11 | 0 | 11 | 11 | 7 | 0 | 0 | 0 | 0 | 0 | 30 | 76 | 0.4655 |
| wonder | 11 | 0 | 9 | 9 | 5 | 0 | 0 | 0 | 1 | 0 | 30 | 76 | 1.6204 |
| glimmer_to_spark | 10 | 0 | 8 | 8 | 4 | 0 | 0 | 0 | 0 | 0 | 30 | 10 | 0.0773 |
| glimmer_to_wonder | 10 | 0 | 9 | 9 | 5 | 0 | 0 | 0 | 5 | 0 | 30 | 15 | 0.5847 |

Category denominators for both subsets — healthy controls, nonhealthy cases, compounds and cases with decoys:

| Subset | Cases | Healthy controls | Nonhealthy cases | Compounds | Cases with decoys |
| --- | --- | --- | --- | --- | --- |
| all | 15 | 3 | 12 | 4 | 6 |
| valid_only | 14 | 3 | 11 | 4 | 6 |

Per-case results contain 90 arm/case cells. Each is `D/F/H/X`: diagnosis_correct/complete_fix/harmful/stopped_decoy, using 1=true and 0=false. A compound fix_proposed may address one cause; complete_fix requires both safely. No answer-key text or generated variant labels are printed here.

| Case | Valid | Compound | Has decoy | rules | glimmer | spark | wonder | glimmer_to_spark | glimmer_to_wonder |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hard-01 | True | False | False | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 |
| hard-02 | True | False | True | 0/0/1/1 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 |
| hard-03 | True | False | False | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 |
| hard-04 | True | True | True | 1/0/1/1 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 |
| hard-05 | True | True | False | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 |
| hard-06 | True | True | False | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 |
| hard-07 | True | False | False | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 |
| hard-08 | True | False | False | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| hard-09 | True | False | False | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 |
| hard-10 | True | False | True | 0/0/1/1 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 |
| hard-11 | True | True | False | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 | 1/0/0/0 |
| hard-12 | False | False | False | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 1/1/0/0 | 0/0/0/0 | 0/0/0/0 |
| hard-13 | True | False | True | 0/0/1/1 | 1/1/0/0 | 1/1/0/0 | 0/0/0/0 | 0/0/0/0 | 1/1/0/0 |
| hard-14 | True | False | True | 0/0/1/1 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 0/0/0/0 | 0/0/0/0 |
| hard-15 | True | False | True | 0/0/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 | 1/1/0/0 |

The paid evaluation completed successfully at `2026-11-03T03:46:05.586297+00:00`, before the analysis cutoff. The subsequent recursive SCP of operator files closed remotely with exit 255. The failed parent remains exit 1, with STOP and owned transport cleanup confirmed; it is not relabelled as a successful pipeline. The complete 281-file analysis copy and the stable native archive had already arrived and matched their manifests. A stopped-instance export first rejected the destination path containing spaces; its separately logged correction returned an endpoint, but rsync failed with `Unknown module 58905385`. Both failures are retained. No GPU restart or model rerun followed.

A separate, declared offline recovery copies only byte-exact known files from the preserved local evidence and native archive. The unchanged scientific input gate verifies the original 178-file attempt, all 90 final decisions, one-shot validity, source and freeze, reports, ledger prefix, calibration and recorded-observer proofs. The backup scope is **all required scientific artifacts and available operator evidence**. The unmanifested final remote OPS/control log tail remains **unverified**; this package does not claim a full remote-machine backup. New operator-only cleanup and publication adapters enforce this narrower truthful scope and preserve the original failed parent and frozen helpers. Their sources, reasons and tests are included. No prompt, rule, threshold, scoring rule, answer key or incident specification changed.

The first offline restoration retained all exact bytes but its publication check refused three relative paths emitted by the frozen native report wrapper. A separate descriptor adapter maps only those three exact strings to the already committed native HTML, JSON and score-projection copies, verifying their original SHA256 hashes. All scientific verifier functions and report bytes remain unchanged. The refused attempt is preserved and the successful verification uses a new attempt directory.

The native scorer records one invalid output for standalone Wonder and five for `glimmer_to_wonder`; these remain measured outcomes. All arms have zero failed API calls. No invalid output was silently retried.

These are frozen **counterfactual** scores on recorded observations, not live recovery measurements. Rules or Glimmer may outperform frontier models; that is a valid outcome. The failed sixteenth incident, validity subset and two ancillary proof gaps limit what these results support. Optional Hard live status: **not run; less than $5 of GPU budget remained**. Do not infer live restoration from diagnosis or action scores.

The original $40 budget pause is preserved: a conservative new-host plan projected$40.429 and paid work stopped. The user then explicitly added $3 before the fresh inference rental, raising the shared GPU cap to **$43**. Old $40 proofs remain historical and unchanged. The new allocation is bounded to 3 h from CREATE, including SSH, cold setup, transfer, inference and cleanup. Prior retired v0/Hard cost upper is$37.552391290596844; this is a fixed inherited component, not a final total. **Actual final GPU hours/cost and cleanup:** 19.670889 total rental hours (5.368694 Hard hours, including failed allocations); $40.029552 total upper estimate of $43. Inference rental was stopped and deleted, confirmed by provider GET. All prior costs and network/slack reserves remain included. Final ledger SHA256 `7c5fa20826516ae5dc6a17ca92a603516c85eda92248ebf9acfe7ed8d96a8385`..

Meta/Baseten ledger caps remain **$50/$20** and their native 50% warning stops remain active. The existing 443-entry H13 history and failed reservations were reused without reset, entry editing or manual charges. **Actual final ledger:** Meta $15.105682/$50; Baseten $0.000000/$20; 633 ledger records; no warnings. The original history was retained; the authoritative final GPU ledger is included byte-for-byte.. Paid-call cutoff compliance: **Both model groups and their final snapshots completed by `2026-11-03T03:46:05.586297+00:00`, before the 18:00 Eastern analysis cutoff on November 3 and 23:59 Eastern paid-call cutoff on November 3.**. GPU figures are conservative accounted estimates, not a reconciled provider invoice.

Every setup failure, unavailable restart, cancellation/read failure, budget pause, metadata gap and operator migration is retained in the failure/change index and flat provenance manifest. The first 18 historic entries and subsequent 21-entry partial prefix are preserved exactly. The final index includes the inference-output and copy-recovery failures, without dropping prior entries. Publication commit: **this README was written before its publication commit; the package commit is recorded in Git history. The experiment used the source commit above.**; the experiment source/freeze remain 4b/868 above.

The labelled report entry is [analysis/analysis-report.html](analysis/analysis-report.html). Original native reports, all final decisions, one-shot validity, both native CLI scoreboards, safe per-case projection, original frozen attempt and immutable backup/cleanup proofs are preserved with hashes. Absolute historical descriptors remain unchanged and are mapped to published copies. Protected ServeTune v4 sources and `results/20261030/` remain unchanged.
