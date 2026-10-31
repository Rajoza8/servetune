# ServeDoctor GPU brief (November 1–2, 2026)

You are running the GPU half of ServeDoctor. Read
[SERVEDOCTOR.md](SERVEDOCTOR.md) first. Code is on branch `servedoctor` of
this repository and is tested offline (`python3 -m unittest discover -s tests -q`).

## Hard limits (set by the user)

- **GPU rental: $40 total for ServeDoctor.** Track hours × hourly price in
  `runs/servedoctor-gpu-hours.md` after every session. Stop or pause the
  instance whenever no command is running. Stop all GPU work and report if the
  projected total would exceed $40.
- **API caps: Meta $50, Baseten $20,** enforced by the ServeDoctor ledger
  (`runs/servedoctor-ledger.json`). Never edit or reset it.
- **Do not touch ServeTune v4** (`results/20261030/`, `servetune/` sources).
- **Never read or print `answers/` in any prompt, and never change answer keys
  or scoring rules after seeing test-split results.**
- No retries that hide failures: a failed incident stays failed and is
  re-recorded under a new run directory with the reason written down.
- Deadline checkpoint: **by noon Eastern on November 2**, dev incidents must be
  recorded and scored by at least the rules and Spark arms. If not, stop and
  report; the user will fall back to the ServeTune submission.

## 0. Machine

Same as ServeTune v4: one RTX PRO 6000 Blackwell 96 GB on Vast, on-demand
(not interruptible), verified host, ≥150 GB disk. Install the Glimmer-capable
vLLM as in the README, then:

```sh
git clone https://github.com/Rajoza8/servetune && cd servetune && git checkout servedoctor
python3 -m pip install -e '.[gpu]'
python3 -m servetune doctor
python3 -m servetune prepare-data --out data/gsm8k
export REV=<exact 40-character Glimmer Hub commit used in v4>
```

## 1. Preflight (about 30 minutes)

1. Start Glimmer with the base config through a short calibration step (step
   2 does this) and confirm in `runs/sd-calibration/engine/engine.log` that it
   serves, and how much KV-cache memory vLLM reports at
   `gpu_memory_utilization=0.9`.
2. Confirm the contention job runs and appears in the GPU process table while
   vLLM is up:
   `python3 -m servedoctor.jobs.embedding_batch --seconds 20 --duty 0.5` and
   `nvidia-smi` in another shell.
3. Initialize the ledger once: `python3 -m servedoctor ledger-init`.
4. Export `MODEL_API_KEY` (Meta) in the shell only. Never write it to a file.

## 2. Calibrate capacity (about 10 minutes)

```sh
python3 -m servedoctor calibrate --model-revision $REV --out runs/sd-calibration
```

It steps the arrival rate (2, 4, … 14 rps, 60 s each) and records the highest
rate meeting the SLO (p95 ≤ 10 s, errors ≤ 1%).

**Check KV-starvation severities now.** `kv_cache_starvation` uses
`gpu_memory_utilization` values 0.80 / 0.78 / 0.76. If Glimmer's weights do not
leave room for KV cache at those values (engine fails to start), or leave so
much that nothing changes, pick three values that start successfully and
leave roughly 15%, 25% and 40% of the base KV capacity. Write the change and
reason into `configs/servedoctor.json` before generating. This is the only
config change allowed without the user, and only before step 3.

## 3. Generate the study

```sh
python3 -m servedoctor generate --calibration runs/sd-calibration/calibration.json --out runs/sd-study
```

Save the printed commitment hashes in your report.

## 4. Record reference and dev incidents (about 1.5 hours)

```sh
python3 -m servedoctor record --model-revision $REV --study-dir runs/sd-study --split reference
python3 -m servedoctor record --model-revision $REV --study-dir runs/sd-study --split dev
python3 -m servedoctor evaluate --study-dir runs/sd-study --split dev --arms rules
python3 -m servedoctor report --study-dir runs/sd-study
```

Open `runs/sd-study/report.html`. For each dev incident, check that the fault
produced visible symptoms (latency, queueing, errors, KV pressure, throughput
drop, or low arrivals for underutilization). If a fault type produced **no**
symptom, you may raise only that type's severities in `configs/servedoctor.json`,
generate a **new** study directory and re-record. Record what changed and why.
Rule thresholds in `servedoctor/rules.py` may be tuned on dev only, before any
test recording, and every change must be listed in your report.

## 5. Dev evaluation of the model arms (about 30 minutes)

```sh
python3 -m servedoctor evaluate --study-dir runs/sd-study --split dev --arms spark
python3 -m servedoctor evaluate --study-dir runs/sd-study --split dev \
  --arms glimmer,glimmer_to_spark --start-glimmer --model-revision $REV
python3 -m servedoctor score --study-dir runs/sd-study --split dev
```

Prompt bugs (for example JSON that never parses) may be fixed on dev only. If you
change prompts, delete `runs/sd-study/decisions/<arm>/` for the dev incidents of
that arm and rerun, and record the change. Freeze prompts after this step.

**Report to the user here (noon checkpoint).**

## 6. Record and evaluate test incidents (about 2.5 hours)

```sh
python3 -m servedoctor record --model-revision $REV --study-dir runs/sd-study --split test
python3 -m servedoctor evaluate --study-dir runs/sd-study --split test --arms rules,spark
python3 -m servedoctor evaluate --study-dir runs/sd-study --split test \
  --arms glimmer,glimmer_to_spark --start-glimmer --model-revision $REV
python3 -m servedoctor report --study-dir runs/sd-study
```

## 7. Live runs (about 2 hours)

Pick one **test** incident per fault type (6 runs) and run the full agent:

```sh
python3 -m servedoctor live --model-revision $REV --study-dir runs/sd-study --id inc-XX --arm glimmer_to_spark
```

If budget remains, run `--arm rules` on the same incidents for comparison.
Each run lasts the incident plus 5 minutes, plus any engine restart. The
monitor in live mode uses the same Glimmer server being repaired, so it is
unavailable during restarts; that is recorded, not hidden.

## 8. Package and push

Copy `runs/sd-study` (including `answers/`, `decisions/`, `live/`, `report.html`)
to `results/servedoctor-20261102/`, excluding model weights and any file with a
credential. Add `results/servedoctor-20261102/README.md` with: hardware, vLLM
version, model revision, commitment hashes, every config/prompt/threshold change
and why, GPU hours and cost, ledger summary, and failures. Commit to branch
`servedoctor` and push.

## Expected GPU time

| Step | Hours |
| --- | --- |
| Setup and preflight | 1 |
| Calibration | 0.3 |
| Reference + dev recording | 1.5 |
| Dev model evaluation | 0.5 |
| Test recording | 2 |
| Test model evaluation | 0.5 |
| Live runs | 2 |
| Slack | 1.2 |
| **Total** | **about 9** |

At $1–2 per hour this is about $9–18, well under the $40 limit.
