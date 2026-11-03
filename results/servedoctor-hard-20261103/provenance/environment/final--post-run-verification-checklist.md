# Post-run verification and publication checklist

This is an inactive operator checklist. None of the commands below were run when this file was prepared. Use it only after the evaluation, final mirrors, relay cleanup and owning pipeline have finished. Read safe projections and aggregates; never display answer keys, runtime truth objects, model responses or whole native reports.

Exact label everywhere: **ServeIncidents-Hard (15 of 16 frozen incidents; hard-16 could not start)**.

## Fixed inputs and helper pins

Run from the repository root. These shell variables are conveniences, not changes to any study or protocol.

```sh
sd_repo='/Users/rajoza/Documents/ChatGPT/meta hackathon/servetune'
sd_ops="$sd_repo/runs/servedoctor-hard15-ops-20261102"
sd_oldops="$sd_repo/runs/servedoctor-hard-ops-20261102"
sd_v0ops="$sd_repo/runs/servedoctor-ops-20261101"
cd "$sd_repo"
```

| Input | Exact path or commitment |
| --- | --- |
| Analysis mirror | `$sd_ops/inference-final-study` |
| Original unchanged 178 files | `$sd_ops/inference-final-original-study` |
| Final remote P / old OPS / control mirrors | `$sd_ops/inference-final-remote-ops`, `inference-final-remote-old-ops`, `inference-final-remote-control` |
| Evaluation proof | `$sd_ops/inference-evaluation-attempt1` |
| Safe score projection | `$sd_ops/inference-evaluation-attempt1/hard15-score-projection.json` |
| Authoritative final ledger for **both** helpers | `$sd_ops/inference-final-gpu-ledger.json` |
| Original ledger prefix | `$sd_oldops/prepare-next-attempt1/upload/ledger.seed`, SHA `13f777ed328bb0c71bb2063b6b12cf3b6cb8024d78b0ab46b9e374521a566123` |
| Calibration mirror | `$sd_ops/inference-final-remote-ops/portable-recording-evidence/calibration` |
| New operator protocol | `$sd_ops/inference-final-study/inference-analysis-protocol.json` |
| One-shot validation marker | `$sd_ops/inference-final-study/inference-validation-dispatch.json` |
| Inference binding / parent outcome | `$sd_ops/inference-rental-attempt1/binding.json`, `outcome.json` |
| Final cleanup output | `$sd_ops/inference-final-cleanup-attempt1` |
| Current hours ledger | `$sd_repo/runs/servedoctor-gpu-hours.md` |
| Package destination, fresh only | `$sd_repo/results/servedoctor-hard-20261103` |

- Experiment source: `4b0add12be36cef0d0776607f683310b1641b0f7`.
- Original freeze: `868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68`.
- Original exclusion: `783ae7be7b60c35146090911ac03d854ad0e5af366c4a178685dbed670a0d1d9`.
- GPU amendment: `8efba5368ca146e45ff55d16fb45567058ae015bcee51a26a5510a0e31c4ee2a`; total GPU cap $43. Meta/Baseten caps remain $50/$20, including native 50% warning stops.
- Recording host remains `58866756` / `GPU-ced6c24c-2234-f9e6-4b0f-6b11b82f9681`; inference is separately bound to `58905385` / scope `7da4c657be8e5e6bf971e5e017a24b02385d6c0f3221daa20ae64e7eb7cedce7`.
- Frozen packager: `package_inference_results.py`, SHA `c98b3fc35f111ce4b852d04dfd362687e5b37aa230c7a2165438f1ef8b8386fc`; proof `package-inference-results-fixtures.json` (13 synthetic fixtures).
- Frozen finalizer: `finalize_inference_rental.py`, SHA `fcbb55ca1b58a810ac87f9991cf5961b5f139f633ecaa10736696495ba5a553c`; proof `finalize-inference-rental-fixtures.json` (31 joint synthetic fixtures).

Do not substitute the old `finalize_partial_rental.py` / `package_partial_results.py` scope gates. The new adapter retains their historical bytes without claiming they passed this new scope.

## 1. Completion and source boundary

Proceed only when the saved evaluation outcome says completed, both groups are present (`rules-spark-wonder`, `glimmer-cascades`), and failure/cleanup errors are empty. Require 90 final decisions across exactly six arms and 15 cases, no partial files, complete context/response proofs and stable full-study/ledger mirror hashes. Invalid JSON and genuine failed calls remain measured results; their counts are not a quality-selection filter.

The parent outcome must have return code 0, confirmed STOP and cleanup, transport cleanup return code 0, and no child/watchdog/transport cleanup failure. Require closed billing intervals and no unresolved mutation. If these conditions fail, retain the failed artifacts and report the failure; do not overwrite an outcome to make a gate pass.

Before a publication commit, source must still be 4b. These commands print no private content:

```sh
git branch --show-current
git rev-parse HEAD
git diff --quiet HEAD -- servedoctor/ servetune/ configs/ docs/SERVEDOCTOR_HARD.md
git diff --quiet 7bb1483deb4c2a801bb397883a4086df8379393b HEAD -- servetune/ results/20261030/
```

Expected branch: `servedoctor`. Do not change the frozen seven inference helpers, original source/config, answer keys, scoring, prompts, rules or thresholds. Do not generate, record, validate again, rerun completed model calls, reset/init the ledger, or regenerate native reports in the final mirror. Native validation already ran once; use its saved result.

The source-prescribed offline test command remains:

```sh
python3 -m unittest discover -s tests -q
```

Use the existing genuine 4b test proof or capture one final offline run in a fresh operator log if needed. Report the actual count/output; do not replace an earlier failing log.

## 2. Read-only finalizer gate, backup, then one DELETE

Create a fresh operator output directory for command streams. Never reuse a failed attempt directory. The finalizer's default mode is read-only; it does not call the provider or write backups. It also verifies owned relay/tunnel quiescence.

```sh
python3 "$sd_ops/finalize_inference_rental.py" --verify-only
```

This verifies the mapped native 15-case validation, original 178 files and retained 16 recordings, all 90 decisions, 8,192-token context fit, response records, all/valid scoreboards, reports, canonical ledger prefix, owning parent and full final mirrors. `verify_inputs(args, repo)` is the shared read-only library gate; its output is counts, SHAs and ledger summary, never answer/model text.

Only after a passing read-only gate, prepare and inspect the complete local backup:

```sh
python3 "$sd_ops/finalize_inference_rental.py" --prepare-backup
python3 "$sd_ops/finalize_inference_rental.py" --verify-only
```

The backup must include `readiness.json`, `backup-manifest.json`, `backup-receipt.json`, immutable `gpu-hours-before-delete.md`, immutable `stopped-state.json`, all verified scientific/evaluation inputs and supplied full mirrors. Current session/heartbeat/hours files are mutable; the snapshots bind the pre-DELETE state. DELETE intent/outcome/reconciliation are future cleanup evidence and must not be required as members of the earlier backup manifest.

The following is the explicit lifecycle boundary, for the root operator only after the backup is verified:

```sh
python3 "$sd_ops/finalize_inference_rental.py" --delete
```

One DELETE only. If the outcome is unknown or absence is not yet confirmed, preserve the dispatch/intent and use GET-only reconciliation:

```sh
python3 "$sd_ops/finalize_inference_rental.py" --reconcile
```

Do not replay `--delete`. Require `cleanup.json` with GET-confirmed absence, stopped/quiescent flags, final state and DELETE lineage, final canonical ledger SHA equal to the remote SHA, final hours-log SHA and recomputed all-host cost at or below $43. The prior $37.552391290596844 stays a fixed inherited component; current compute/disk is added once and network/slack is not counted twice.

## 3. Safe aggregate cross-checks and finalized publication evidence

After completion, the saved canonical boards are:

- `$sd_ops/inference-evaluation-attempt1/final-score-all.stdout`
- `$sd_ops/inference-evaluation-attempt1/final-score-valid_only.stdout`
- `$sd_ops/inference-evaluation-attempt1/final-ledger.stdout`

If an independent local canonical score cross-check is wanted, these commands are read-only and print aggregate boards only:

```sh
python3 -m servedoctor score --study-dir "$sd_ops/inference-final-study" --split hard
python3 -m servedoctor score --study-dir "$sd_ops/inference-final-study" --split hard --valid-only
```

Compare their JSON to the saved final boards and safe projection. Do not print whole `answers/`, decision trails/raw responses or native `report.json`; the trusted packager compares their required fields programmatically. Use actual final validity denominators rather than assuming all 15 are valid.

Create fresh finalized evidence files from the retained drafts; do not edit the drafts or historical rows. Preserve the original 18-entry history, 21-entry partial prefix, and subsequent 28/29-entry draft history exactly, then append actual final outcomes. The final failure index must say `finalized: true`. Every failure artifact and final cleanup/evaluation/helper/transport proof must have an explicit flat provenance destination and matching SHA. See `final-evidence-additions-checklist.json` for the separate exact-additions inventory. `finalize_inference_provenance.py` is a separate new helper owned by the root/API agent; use its reviewed final interface once available.

The README renderer requires these inputs; its output path must be fresh. Set the three publication paths below to the **actual finalized files** returned by the evidence finalization step, not draft files:

```sh
sd_final_failures='<actual finalized inference failure-index JSON>'
sd_final_provenance='<actual finalized flat provenance JSON>'
sd_final_readme='<fresh final README.md path under the operator directory>'

python3 "$sd_ops/render_inference_readme.py" \
  --template "$sd_ops/inference-README.template.md" \
  --projection "$sd_ops/inference-evaluation-attempt1/hard15-score-projection.json" \
  --cleanup "$sd_ops/inference-final-cleanup-attempt1/cleanup.json" \
  --protocol "$sd_ops/inference-final-study/inference-analysis-protocol.json" \
  --hardware "$sd_ops/inference-final-remote-ops/inference-hardware.json" \
  --hardware-progress "$sd_ops/inference-progress-attempt1/snapshot-0001.stdout" \
  --prior "$sd_ops/inactive-host5-backup-attempt1/destroy-receipt.json" \
  --v0 "$sd_v0ops/destroy-receipt-58716527.json" \
  --failures "$sd_final_failures" \
  --evaluation "$sd_ops/inference-evaluation-attempt1/outcome.json" \
  --optional "$sd_ops/optional-live-skipped-budget-attempt1.json" \
  --out "$sd_final_readme"
```

Use the complete final hardware JSON, not the extensionless preparation copy as a published source. `inference-doc-progress-validation14of15.json` is not the renderer's hardware-progress schema. The renderer permits `not-run-budget-below-5` only when actual remaining GPU budget is below $5; do not force that status if final accounting differs.

The rendered README must retain the partial label, all/valid boards and denominators, D/F/H/X semantics, counterfactual-not-live interpretation, original failed hard-16 reason, recording/inference hardware separation, two missing ancillary metadata files, old/new transport distinction, ledger warnings/cost, failures and publication-versus-experiment commit distinction. Do not claim the missing readiness JSON was recovered or that the old full freeze gate passed.

## 4. Package verification, fresh creation, commit and push

**Always pass the final GPU ledger path explicitly.** The packager's default evaluation ledger may be byte-identical but has a different path-keyed backup inventory from the frozen finalizer.

First, verification only:

```sh
python3 "$sd_ops/package_inference_results.py" \
  --score-projection "$sd_ops/inference-evaluation-attempt1/hard15-score-projection.json" \
  --evaluation-dir "$sd_ops/inference-evaluation-attempt1" \
  --ledger "$sd_ops/inference-final-gpu-ledger.json" \
  --cleanup-evidence "$sd_ops/inference-final-cleanup-attempt1/cleanup.json" \
  --provenance "$sd_final_provenance" \
  --readme "$sd_final_readme"
```

Only after `verified: true`, run the identical command with `--create`. It creates the fresh `results/servedoctor-hard-20261103/` tree once, preserving original/analysis bytes, selected provenance, ledger and manifest. Existing or partially failed destinations are retained and refused. Never delete a failed package to hide it.

Before committing, check the created `package-manifest.json` hashes, `artifact-index.json`, labelled `analysis/analysis-report.html` entry, original 178-file tree, ledger and final cleanup, plus the selected-file privacy scan. No private keys, environment dumps, model weights or recursive private OPS backups should be staged. The worker source remains hash-bound by protocol/proofs rather than published recursively.

The publication commit is a **later** commit than the 4b experiment. Finish all source-HEAD-sensitive gates above before committing. Do not restamp the original freeze/protocol to the publication commit, and do not interpret a later HEAD mismatch as permission to alter an old proof.

```sh
git add results/servedoctor-hard-20261103/
git diff --cached --name-only
git diff --cached --stat
git commit -m "Publish ServeIncidents-Hard fifteen-case analysis"
git push origin servedoctor
```

Stage only the reviewed new result tree. Confirm the branch and staged paths before the commit; preserve unrelated user changes. After pushing, report actual run/package paths, both native boards, ledger summary, all GPU hours/dollars, original changes/exclusion/transport and budget amendments, failures/open problems, any remaining decision and the publication commit. Do not make an unsupported superiority or live-restoration claim.
