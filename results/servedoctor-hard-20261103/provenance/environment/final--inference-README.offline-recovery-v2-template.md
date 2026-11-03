# ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)

**DRAFT — final score projection, ledger and cleanup evidence are pending. Do not publish this template.**

This is the explicitly approved analysis of the fifteen completed incidents from the original sixteen-incident Hard specification. One reference and `hard-01` through `hard-15` were recorded. `hard-16` could not start; the original attempt remains preserved and is not represented as a full sixteen-case result. The exclusion was recorded at `2026-11-02T23:07:44.538859+00:00`, before any native Hard validation or model-arm evaluation. Native prompts, rules, thresholds, answer keys and scoring did not change.

The failed engine used frozen KV utilization `0.61632` with a generated `max_num_batched_tokens=12288`, whereas the standalone pre-generation calibration used8192. vLLM reported **-0.54 GiB** available KV cache; cleanup left2MiB and no compute process. The incident was not retuned, regenerated or re-recorded. The original16 key/scenario bytes, freeze and failed startup are retained under `original-frozen-attempt/`.

The measurements were made on recording instance `58866756`, physical GPU `GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681`. Before generation, that host was calibrated to6RPS; the unchanged mild/compound standalone KV values0.61632/0.61520 gave p95 10.004323831864165s/15.239633663152924s, with268/268 requests successful in each. The original host was later unavailable for a queued restart and was retired after its available local scientific evidence was backed up. Its later remote OPS/control tail was explicitly unverified.

Inference runs separately on verified Texas instance `58905385`, scope `7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7`. Actual inference GPU UUID: **{{INFERENCE_GPU_UUID}}**; driver/vLLM: **{{INFERENCE_DRIVER_AND_VLLM}}**. No new generation, calibration, benchmark recording or scientific configuration change occurred on this inference host. Both hosts use the pinned RTX PRO6000 Blackwell96GB environment, BF16 Glimmer30B revision `cec94fcfd6512f2cfe708138c32533b346ea4f69`; exact hardware/runtime proofs accompany the package.

| Frozen item | Value |
| --- | --- |
| Recording/evaluation source | `4b0add12be36cef0d0776607f683310b1641b0f7` |
| Original config SHA256 | `0cc70e7ec4cbb0b26c6e13a4b9311dedf6dd05a862d9c0d9d2934ec25a017014` |
| Original 16 answer commitment | `fb168177884005df77a94cbb75e6d52946a26ccfc3675db82820bb9105eaadc0` |
| Original 16 scenario commitment | `bbd1f792878602f6472e56a5795f9f257882ad541b3184ce38af00588c4d3f20` |
| Original 16 freeze SHA256 | `868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68` |
| Pre-validation exclusion SHA256 | `783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9` |
| Dated GPU budget amendment SHA256 | `8efba5368ca146e45ff55d16fb45567058ae015bcee51a26a5510a0e31c4ee2a` |
| New operator inference protocol SHA256 | `{{INFERENCE_PROTOCOL_SHA256}}` |

Two historical ancillary raw JSON files remain unavailable: `preflight-readiness.json` (`142e8954…`) and its declaration JSON (`8b5534f7…`). Their commitments, successful readiness stdout and the failed stopped-host recovery attempt remain recorded. The original 178 files, sixteen recording manifests, 112 sealed payload files and owned-observer proofs were verified separately. The portable operator gate explicitly discloses the two gaps and **does not claim the old full verify_freeze gate passed**. Original descriptors and freeze bytes were not rewritten to conceal missing evidence.

The original three API transport files were bound to the recording host. Only the analysis copy archives those exact bytes at `operator-provenance/original-api-transport/`, then freezes a new-instance transport trio. Spark and Wonder use a TLS-blind Mac CONNECT relay to the fixed official `api.meta.ai:443` endpoint. The relay sees no Bearer credential or model body; the diagnostic GET uses the same verified native CONNECT transport as paid calls. Model IDs, per-token rates, native messages and payload parameters are unchanged. Spark is `muse-spark-1.3` at$1.25 input/$4.25 output per million tokens; Wonder is `muse-wonder-1.0` at$4/$20. [Official model IDs](https://dev.meta.ai/docs/models) and [standard pricing](https://dev.meta.ai/docs/pricing-rate-limits) were rechecked before inference; the exact receipt is preserved.

**Actual validity:** {{VALID_CASES}} valid and {{INVALID_CASES}} invalid, out of15 retained cases. The unchanged native rule was run once before arm evaluation. Invalid symptoms remain in the all15 scoreboard, and valid-only uses the same decisions. **Actual coverage:** {{FINAL_DECISION_COVERAGE}}. Failed calls remain recorded canonical failures; invalid JSON remains an invalid model result. No model output was silently retried or dropped.

All15 scoreboard (`python3 -m servedoctor score --study-dir runs/sd-hard-partial-attempt1 --split hard`):

{{ALL_SCOREBOARD}}

Valid-only scoreboard (same command with `--valid-only`):

{{VALID_SCOREBOARD}}

Category denominators for both subsets — healthy controls, nonhealthy cases, compounds and cases with decoys:

{{CATEGORY_DENOMINATORS}}

Per-case results contain90 arm/case cells. Each is `D/F/H/X`: diagnosis_correct/complete_fix/harmful/stopped_decoy, using 1=true and 0=false. A compound fix_proposed may address one cause; complete_fix requires both safely. No answer-key text or generated variant labels are printed here.

{{PER_CASE_DFHX_TABLE}}

The paid evaluation completed successfully at `2026-11-03T03:46:05.586297+00:00`, before the analysis cutoff. The subsequent recursive SCP of operator files closed remotely with exit 255. The failed parent remains exit 1, with STOP and owned transport cleanup confirmed; it is not relabelled as a successful pipeline. The complete 281-file analysis copy and the stable native archive had already arrived and matched their manifests. A stopped-instance export first rejected the destination path containing spaces; its separately logged correction returned an endpoint, but rsync failed with `Unknown module 58905385`. Both failures are retained. No GPU restart or model rerun followed.

A separate, declared offline recovery copies only byte-exact known files from the preserved local evidence and native archive. The unchanged scientific input gate verifies the original 178-file attempt, all 90 final decisions, one-shot validity, source and freeze, reports, ledger prefix, calibration and recorded-observer proofs. The backup scope is **all required scientific artifacts and available operator evidence**. The unmanifested final remote OPS/control log tail remains **unverified**; this package does not claim a full remote-machine backup. New operator-only cleanup and publication adapters enforce this narrower truthful scope and preserve the original failed parent and frozen helpers. Their sources, reasons and tests are included. No prompt, rule, threshold, scoring rule, answer key or incident specification changed.

The first offline restoration retained all exact bytes but its publication check refused three relative paths emitted by the frozen native report wrapper. A separate descriptor adapter maps only those three exact strings to the already committed native HTML, JSON and score-projection copies, verifying their original SHA256 hashes. All scientific verifier functions and report bytes remain unchanged. The refused attempt is preserved and the successful verification uses a new attempt directory.

The native scorer records one invalid output for standalone Wonder and five for `glimmer_to_wonder`; these remain measured outcomes. All arms have zero failed API calls. No invalid output was silently retried.

These are frozen **counterfactual** scores on recorded observations, not live recovery measurements. Rules or Glimmer may outperform frontier models; that is a valid outcome. The failed sixteenth incident, validity subset and two ancillary proof gaps limit what these results support. Optional Hard live status: **{{OPTIONAL_LIVE_STATUS}}**. Do not infer live restoration from diagnosis or action scores.

The original$40 budget pause is preserved: a conservative new-host plan projected$40.429 and paid work stopped. The user then explicitly added$3 before the fresh inference rental, raising the shared GPU cap to **$43**. Old $40 proofs remain historical and unchanged. The new allocation is bounded to3h from CREATE, including SSH, cold setup, transfer, inference and cleanup. Prior retired v0/Hard cost upper is$37.552391290596844; this is a fixed inherited component, not a final total. **Actual final GPU hours/cost and cleanup:** {{FINAL_GPU_ACCOUNTING_AND_CLEANUP}}.

Meta/Baseten ledger caps remain **$50/$20** and their native50% warning stops remain active. The existing443-entry H13 history and failed reservations were reused without reset, entry editing or manual charges. **Actual final ledger:** {{FINAL_LEDGER_SUMMARY}}. Paid-call cutoff compliance: **{{PAID_CUTOFF_EVIDENCE}}**. GPU figures are conservative accounted estimates, not a reconciled provider invoice.

Every setup failure, unavailable restart, cancellation/read failure, budget pause, metadata gap and operator migration is retained in the failure/change index and flat provenance manifest. The first18 historic entries and subsequent21-entry partial prefix are preserved exactly. The final index includes the inference-output and copy-recovery failures, without dropping prior entries. Publication commit: **{{PUBLICATION_COMMIT_OR_LATER_COMMIT_DISCLOSURE}}**; the experiment source/freeze remain4b/868 above.

The labelled report entry is [analysis/analysis-report.html](analysis/analysis-report.html). Original native reports, all final decisions, one-shot validity, both native CLI scoreboards, safe per-case projection, original frozen attempt and immutable backup/cleanup proofs are preserved with hashes. Absolute historical descriptors remain unchanged and are mapped to published copies. Protected ServeTune v4 sources and `results/20261030/` remain unchanged.
