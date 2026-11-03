# ServeTune measured results · October 30, 2026

**Neither Spark-guided tuning nor random search found an accepted energy improvement over their shared FP8 starting configuration.** Both retained FP8 defaults. This is a completed experiment with a negative tuning result.

The original study was sealed and verified: **111 live trial observations**, including failures, with **zero synthetic observations**. All five phases—calibration, performance map, BF16/FP8 comparison, tuning, and fresh confirmation—are complete. The current download is a **curated public snapshot** with internal setup material archived privately and a new publication manifest. Every retained scientific payload and all trial and preflight seals are unchanged.

## Fresh confirmation

These are medians across five fresh repeats per unique configuration at the frozen high-load workload. The two selected search configurations both alias FP8 defaults; they were not measured again as extra independent configurations.

| Configuration | GPU J/output token | GPU J/completed request | p95 latency (seconds) | Final quality |
| --- | ---: | ---: | ---: | ---: |
| BF16 defaults | 0.468540 | 59.9731 | 6.3579 | 284/300 |
| FP8 defaults | 0.466332 | 59.6827 | 3.2084 | 285/300 |

FP8 used **0.471% less GPU energy per output token** and had **49.54% lower p95 latency** than BF16 in this confirmation. The energy difference is below the study's strict greater-than-2% minimum for accepting a tuning improvement. Each unique configuration used the held-out 300-question final set once. Both passed the predeclared 2-percentage-point count tolerance; that is not a statistical equivalence claim.

Energy means **GPU energy measured through NVML**. These observations apply to one physical RTX PRO 6000 Blackwell Workstation GPU, one pinned Muse Glimmer model and vLLM revision, and the frozen math workload. They do not establish whole-system energy reductions, rental bill reductions, or results on other hardware and workloads.

## Search comparison

| Search arm | Allocated time | Recorded time charged | Candidate attempts | Accepted changes |
| --- | ---: | ---: | ---: | ---: |
| Random search | 6 hours | 4.946 hours | 9 | 0 |
| Meta Muse Spark 1.3 | 6 hours | 4.917 hours | 8 | 0 |

Both arms had the same starting configuration, finite search space, fixed workload, acceptance gates, and allocated time. Allocated time includes planning, engine startup, warmup, measurements, quality evaluation and failures. The admission rule stopped search before another complete candidate could fit while preserving final confirmation. Failed and rejected attempts remain in the evidence.

The completed v4 measurement deliverable includes the three-load energy map, BF16/FP8 comparison, sealed trial records, and offline replay. Its completion does not mean that tuning produced energy savings or that Spark beat random search.

## Reports and replay

- [Measured results and final paired quality](report/results.md)
- [All trial observations](report/trials.csv) and [fresh confirmation observations](report/headline.csv)
- [Search decisions](report/decisions.csv)
- [Measurement deliverable verification](report/floor.md)
- [Offline interactive dashboard](report/dashboard.html) — download and open locally
- [Three-minute demo video](report/demo/servetune-demo.mp4) and [narration](report/demo/narration.md)
- [Provider API accounting summary](provider-ledger-summary.json)
- [Archive hashes and per-member inventory](evidence/archive-manifest.json)
- [Public curation receipt and exact exclusions](evidence/curation-receipt.json)

Meta API accounting is **$0.059826** for one preflight call and eight tuning calls. Baseten accounting is **$0**. These are token-based estimates with no unresolved reservations; they are not provider invoices.

From the repository root, verify the current download, its retained original payload hashes, and the native scores:

```sh
python3 scripts/verify_public_evidence.py
```

This uses temporary disk space of approximately 1.2 GB and requires no GPU, credentials or API calls. It verifies **111 live trials and 10 fresh confirmation observations**, with the same decisions, quality results and measured comparisons as the original full study.

For a persistent local extraction, concatenate the three **public-evidence** parts in the order listed in `evidence/archive-manifest.json`, verify the SHA256 below, and extract into an empty directory. From this results directory:

```sh
cat evidence/public-evidence.tar.gz.part001 evidence/public-evidence.tar.gz.part002 evidence/public-evidence.tar.gz.part003 > public-evidence.tar.gz
shasum -a 256 public-evidence.tar.gz
```

Current curated archive SHA256: `6092c154c99a6ff3a3768795165bdfef7e9d19af85e47e80ee79247eeae9511f`.

After extraction, run `python3 -m servetune study-replay /path/to/extracted/study` from a ServeTune source checkout. This checks the new publication manifest and the unchanged trial seals. It does not verify the historical original root seal against the curated file set.

Derived study manifest SHA256: `baa2517258aba5d120c231546c3760fe470dfb018979548b7ae05ecdd9f0fd5b`.

Historical original archive SHA256: `1cc4cbfd6f0b128374a6968228a69e719ce37a62a3d0ef04d776d18594f634e8`.

Original sealed study manifest SHA256: `f2361671b3e32f6d3b0ca3ffceacd18f470bce0164e73ba3c0e1ae7293f9ef29`.

The [original member inventory](evidence/original-archive-manifest.json) and [original study manifest](evidence/original-study-manifest.json) remain public as historical commitments outside the extracted study. The complete original package is retained in the private `servetune-internal` archive and in unchanged historical Git commits. Current-public cleanup does not erase those historical commits.

The curated archive omits ten internal setup, build-note and recovery-helper files. It retains all trials, requests, energy readings, quality outcomes, search histories, frozen protocols, licensed public data, and sealed scientific source snapshots byte for byte. Only the outer `study/manifest.json` is replaced to describe this narrower publication. The curation receipt records every exclusion and its original hash, the new identities, and the successful original and derived native replay checks. This packaging work adds no measurements or model calls.
