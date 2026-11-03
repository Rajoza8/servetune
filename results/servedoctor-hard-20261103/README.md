# ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)

All six arms were evaluated on the fifteen completed Hard incidents, producing
**90/90** final arm/case decisions. Standalone Glimmer and Spark each diagnosed
11/12 nonhealthy incidents correctly; Wonder diagnosed 10, Glimmer→Wonder 9,
Glimmer→Spark 8 and rules 7. Every model arm made zero harmful proposals; rules
stopped a harmless GPU job in **5 of 6** cases containing decoys. No arm proposed
a safe complete fix for any of the four compound incidents.

These are frozen counterfactual scores on recorded observations. Hard live
repairs were **not run**. Diagnosis and proposed-action scores do not establish
service recovery or general model superiority.

## Reproduce the scores

From the repository root, without a GPU, API key or model calls:

```sh
python3 -m servedoctor score --study-dir results/servedoctor-hard-20261103/analysis --split hard
python3 -m servedoctor score --study-dir results/servedoctor-hard-20261103/analysis --split hard --valid-only
python3 scripts/build_site.py
```

The labelled [analysis report](analysis/analysis-report.html) and
[analysis JSON](analysis/analysis-report.json) retain both scoreboards.
[analysis/report.json](analysis/report.json) contains the native per-case scores.
[The design](../../docs/SERVEDOCTOR_HARD.md) describes compound scoring,
decoys, config noise and the predeclared symptom check.

## Frozen design, host calibration and exclusion

Hard was designed after v0 saturated. It adds harmless engine-config changes,
decoy jobs with the same ordinary names as contention jobs, four two-cause
incidents, near-threshold faults and red herrings. Prompts, models, rule
thresholds, action rules and scoring were frozen from v0. The Hard set has no
development split; nothing was tuned on its agent outputs.

Recording used an RTX PRO 6000 Blackwell 96 GB,
GPU `GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681`. Before generation, measured
capacity was **6 requests/s**. The mild/compound standalone KV utilization
values `0.61632` / `0.61520` gave successful-request p95 latency
10.004323831864165 / 15.239633663152924 seconds, with 268/268 requests
successful in each probe. The values were frozen before generation.

One reference and `hard-01` through `hard-15` were recorded. `hard-16` could not
start: the generated benign `max_num_batched_tokens=12288` interacted with
frozen KV utilization `0.61632`, while standalone calibration had used 8192.
vLLM reported **−0.54 GiB** available KV cache; cleanup left 2 MiB and no compute
process. This is a generator defect, not a model outcome. The incident was not
retuned, regenerated or re-recorded. Its exclusion was recorded at
`2026-11-02T23:07:44.538859+00:00`, **before symptom validation or model-arm
evaluation**. The full frozen 16-case keys, scenarios, freeze and failed startup
remain in [original-frozen-attempt/](original-frozen-attempt/); the 15-case
analysis is explicitly separate rather than a claimed complete 16-case result.

Inference later ran on a separate RTX PRO 6000 Blackwell 96 GB,
GPU `GPU-a38fda97-350c-5724-46e6-82b87f985a96`, driver `610.43.02`, vLLM
`0.26.1rc1.dev608+g99a10304d`. No new generation, calibration, benchmark recording
or scientific configuration change occurred on the inference host. Both hosts
used BF16 `meta-models/Muse-Glimmer-30B`, with model and tokenizer pinned to
`cec94fcfd6512f2cfe708138c32533b346ea4f69`. Recording and inference hardware
proofs remain in the public provenance subset. Hard's 6-RPS recording host
also differs from v0's 8-RPS host; cross-study scores are not like-for-like.

| Frozen item | Value |
| --- | --- |
| Recording/evaluation source | `4b0add12be36cef0d0776607f683310b1641b0f7` |
| Original config SHA256 | `0cc70e7ec4cbb0b26c6e13a4b9311dedf6dd05a862d9c0d9d2934ec25a017014` |
| Original 16 answer commitment | `fb168177884005df77a94cbb75e6d52946a26ccfc3675db82820bb9105eaadc0` |
| Original 16 scenario commitment | `bbd1f792878602f6472e56a5795f9f257882ad541b3184ce38af00588c4d3f20` |
| Original 16 freeze SHA256 | `868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68` |
| Pre-validation exclusion SHA256 | `783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9` |

The [commit map](../COMMIT_MAP.md) relates historical source IDs to the current
metadata-normalized commits. Result-publication commits are distinct from the
frozen experimental source.

## Validity and scoring

The unchanged symptom rule ran once before arm evaluation: **14 valid and
1 invalid** among the 15 retained cases. `hard-12` had no SLO breach and remains
in the all-incident scoreboard; valid-only scoring uses the same saved
decisions and removes that case without rerunning a model. Both denominators
and all 90 per-case cells are shown below. Naming either cause counts as a
correct compound diagnosis; a complete fix must safely address both.

All 15 scoreboard (`python3 -m servedoctor score --study-dir results/servedoctor-hard-20261103/analysis --split hard`):

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

## Invalid outputs and transport

Standalone Wonder produced one invalid output and Glimmer→Wonder five. All six
used the fixed **2,048 completion-token cap**, spending most output tokens on
reasoning before a valid answer was available. They remain in the checkpoint
journals and API accounting. Continuing at later recorded checkpoints is
visible in those journals; no invalid output was silently replaced or dropped.
All six arms have zero failed API calls in this completed evaluation.

Spark used `muse-spark-1.3` at historical rates of $1.25 input / $4.25 output
per million tokens; Wonder used `muse-wonder-1.0` at $4 / $20. IDs and rates
were rechecked before inference. Native messages, payload settings and prices
were unchanged. Paid calls used a Mac-origin CONNECT relay to the fixed
`api.meta.ai:443` endpoint with verified end-to-end TLS; the relay saw no Bearer
credential or plaintext model body. The diagnostic GET used the same transport
as paid calls. Host-bound transport descriptors changed only in the analysis
copy when inference moved hosts; the original frozen descriptors were not
rewritten. Operational transport setup belongs to the private development
archive, while retained receipts document the scientific execution context.

## Missing evidence and copy failures

Two historical ancillary raw JSON files are unavailable:
`preflight-readiness.json` (commitment prefix `142e8954…`) and its declaration
JSON (`8b5534f7…`). Commitments and successful readiness stdout survive, but the
raw descriptors were not recovered. Before public curation, the original
178-file attempt, sixteen recording manifests, 112 sealed payload files and
owned-observer proofs were verified separately. That narrower gate explicitly
disclosed the two gaps and **did not claim the old full `verify_freeze` gate
passed**. No original descriptor or freeze was rewritten to hide them.

The recording host later became unavailable; its final unmanifested remote
operations/control log tail remains **unverified**. Inference completed at
`2026-11-03T03:46:05.586297+00:00`. A subsequent recursive SCP of operator files
failed with remote exit 255 and parent exit 1. A stopped-host export first
rejected a destination containing spaces, then its corrected attempt failed
with `Unknown module 58905385`. These are retained procedural failures, not a
successful full pipeline. The historical 281-file analysis copy and native
archive had already arrived and matched their manifests; those counts precede
public curation.

A declared offline recovery used only byte-exact existing local evidence and
the native archive. It verified the scientific inputs, 90 final decisions,
one-shot validity, reports, ledger prefix, calibration and observer proofs.
No GPU restart, model rerun or changed prompt, rule, score, answer key or
incident followed. The first publication check rejected three historical
relative report paths. A separate descriptor mapping resolved only those
strings to the existing HTML, JSON and score-projection copies and checked
their original SHA256 hashes. The failed attempt remains separate from the
later successful scientific verification. None of these checks proves a full
remote-machine or original operator-package backup.

## Accounting and limitations

The final cumulative ledger contains **633 records**, **Meta $15.105682** and
Baseten $0, including the earlier v0 history and retained failed reservations.
Its SHA256 is
`7c5fa20826516ae5dc6a17ca92a603516c85eda92248ebf9acfe7ed8d96a8385`.
These amounts must not be added to v0's earlier cumulative snapshot. The shared
GPU accounting snapshot reports 19.670889 rental hours, including 5.368694
Hard hours and failed allocations, with a $40.029552 upper estimate including
prior costs and reserves. Local accounting and reserved amounts are distinct
from reconciled provider invoices.

The result covers a small, deliberately constructed incident set, one served
model and one engine build. Rules or local Glimmer may outperform frontier
models on these incidents. The failed sixteenth incident, ineffective
`hard-12`, two missing readiness descriptors, six invalid Wonder outputs and
unverified final remote control tail limit the evidence. Zero harmful model
proposals here does not establish general safety. No Hard live recovery,
statistical significance or generalization claim is made.

## Public package scope

The public subset retains original and analysis incident recordings, sealed
answers, all final decisions, one-shot validity, native reports, scoreboards,
calibration and scientific failure evidence. Internal operator scripts,
runbooks, dispatch records and rental administration were moved to a separate
private development archive. Scientific payload bytes are unchanged.
[curation.json](curation.json) records the curation and
[package-manifest.json](package-manifest.json) describes the current public
subset. Historical descriptors can reference private or unavailable operational
files; this release does not assert the old full operator closure or that every
originally packaged file remains public.
