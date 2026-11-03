# Running ServeDoctor on a GPU

The committed [v0](../results/servedoctor-20261102/README.md) and
[Hard](../results/servedoctor-hard-20261103/README.md) results can be scored
offline without a GPU or API key. This guide covers recording a **new** study
and evaluating its agents. New recordings are separate evidence from the
published studies.

## Prerequisites

- Python 3.11 or later and the repository checked out locally.
- A Glimmer-capable vLLM environment, compatible NVIDIA drivers and NVML
  access. The published recordings used one RTX PRO 6000 Blackwell 96 GB,
  BF16 Muse Glimmer 30B and a pinned vLLM build; exact runtime identities are
  retained in the result packages.
- Space for the model weights, Hugging Face cache and recordings. The BF16
  weights are approximately 60 GB.
- Exclusive use of the serving GPU during calibration and recording, except
  for the contention jobs intentionally launched by the benchmark.

Install the harness in the same environment as vLLM:

```sh
python3 -m pip install -e '.[gpu]'
python3 -m servetune doctor
python3 -m servetune prepare-data --out data/gsm8k
```

`prepare-data` downloads the public GSM8K data and its license. It does not
download model weights. Install a Glimmer-compatible vLLM environment separately;
the harness records the installed version rather than replacing it.

The published studies used Glimmer revision
`cec94fcfd6512f2cfe708138c32533b346ea4f69`. Prefetch the immutable revision
before recording, then enable the pinned environment's offline cache resolution:

```sh
export SERVEDOCTOR_MODEL_REVISION=cec94fcfd6512f2cfe708138c32533b346ea4f69
python3 -c 'import os; from huggingface_hub import snapshot_download; snapshot_download("meta-models/Muse-Glimmer-30B", revision=os.environ["SERVEDOCTOR_MODEL_REVISION"])'
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
export VLLM_NO_USAGE_STATS=1
ulimit -n 65536
```

Use the same Hugging Face cache throughout. Verify the model and tokenizer
revision in the engine logs. The file-descriptor setting supplies headroom for
the open-loop client and telemetry collectors; child processes must inherit it.
The harness starts and stops its own vLLM process groups and requires an unused
serving port.

## Calibrate and freeze a v0 study

Run from the repository root and use fresh output directories:

```sh
python3 -m servedoctor calibrate \
  --model-revision "$SERVEDOCTOR_MODEL_REVISION" \
  --out runs/sd-calibration
python3 -m servedoctor generate \
  --calibration runs/sd-calibration/calibration.json \
  --out runs/sd-study
```

Calibration estimates the base workload's capacity. Fault settings in
`configs/servedoctor.json`, especially KV-memory utilization, were calibrated
for the published host and may not transfer to another host or engine build.
Use development recordings or separate pre-generation probes to establish
effective severities. A configuration change requires a new study directory;
preserve the prior attempt and record the change. Freeze the final
configuration, prompts and rules before recording or evaluating test incidents.

Generation writes the study configuration, scenarios, commitment hashes and
sealed answer keys. Agents receive observations built from recordings, not the
answer keys. Do not include answer files in model prompts.

## Record and evaluate development incidents

```sh
python3 -m servedoctor record \
  --model-revision "$SERVEDOCTOR_MODEL_REVISION" \
  --study-dir runs/sd-study --split reference
python3 -m servedoctor record \
  --model-revision "$SERVEDOCTOR_MODEL_REVISION" \
  --study-dir runs/sd-study --split dev
python3 -m servedoctor evaluate \
  --study-dir runs/sd-study --split dev --arms rules,glimmer \
  --start-glimmer --model-revision "$SERVEDOCTOR_MODEL_REVISION"
python3 -m servedoctor score --study-dir runs/sd-study --split dev
python3 -m servedoctor report --study-dir runs/sd-study
```

The rules and local Glimmer arms make no provider API calls. Local Glimmer
evaluation starts a separate healthy server with an 8,192-token context by
default. Recording retains the study's engine settings. Failed recordings and
model outputs remain part of the study history; incomplete collection does not
qualify as a completed recording.

## Evaluate paid expert arms

Spark and Wonder use the Meta Model API. Initialize one persistent ServeDoctor
ledger and provide a key through `MODEL_API_KEY` or `META_API_KEY` in the shell
environment. `.env` files are not loaded automatically. Keep the ledger when
moving between machines so its cumulative accounting remains intact.

```sh
python3 -m servedoctor ledger-init
export META_WONDER_MODEL=muse-wonder-1.0
python3 -m servedoctor evaluate \
  --study-dir runs/sd-study --split dev \
  --arms spark,wonder,glimmer_to_spark,glimmer_to_wonder \
  --start-glimmer --model-revision "$SERVEDOCTOR_MODEL_REVISION"
```

These evaluation commands make paid requests. The published evaluation used
`muse-spark-1.3` and `muse-wonder-1.0`; the explicit Wonder override avoids the
older default alias. The client reserves worst-case cost before dispatch and
retains failed-call reservations. Configured token rates and local accounting
are estimates rather than a provider invoice. Model IDs and rates are defined
in `servedoctor/llm.py`.

## Record and evaluate the frozen test split

After development is complete, retain the frozen prompts, rules, severities,
model settings and scoring code for test evaluation:

```sh
python3 -m servedoctor record \
  --model-revision "$SERVEDOCTOR_MODEL_REVISION" \
  --study-dir runs/sd-study --split test
python3 -m servedoctor evaluate \
  --study-dir runs/sd-study --split test \
  --arms rules,glimmer,spark,wonder,glimmer_to_spark,glimmer_to_wonder \
  --start-glimmer --model-revision "$SERVEDOCTOR_MODEL_REVISION"
python3 -m servedoctor score --study-dir runs/sd-study --split test
python3 -m servedoctor report --study-dir runs/sd-study
```

The score command reads saved decisions and makes no model calls. An arm's
first incident decision is final. Recorded-incident fix scores judge proposed
actions; they do not demonstrate live service recovery.

## Hard studies and live repairs

[SERVEDOCTOR_HARD.md](SERVEDOCTOR_HARD.md) describes the Hard generator, compound
scoring and symptom validation. For a new Hard study, use `generate-hard` with
the new host's calibration, record its reference and Hard splits, then run
`validate` once before arm evaluation or scoring. Report both all-incident and
`--valid-only` scores using the same saved decisions. The published generator
produced one combination that could not start; the result package retains that
failure and the pre-scoring exclusion rather than claiming a complete
16-incident recording.

Live mode applies an arm's proposed actions and measures recovery on new
requests. Choose an incident ID from the new study and a fresh output path:

```sh
python3 -m servedoctor live \
  --model-revision "$SERVEDOCTOR_MODEL_REVISION" \
  --study-dir runs/sd-study --id TEST_INCIDENT_ID \
  --arm glimmer_to_spark --out runs/sd-live-case
```

`TEST_INCIDENT_ID` is a placeholder for a test incident in that study. This
command starts GPU serving and makes paid Spark calls when the local monitor
escalates. Actions are restricted to the harness whitelist; failed recovery
triggers rollback and escalation. Canonical recovery checks successful-request
latency and admitted-request errors, excluding the shed-rate cap. Report
shedding separately. The published live results cover six v0 incidents per
arm; Hard results are recorded-incident evaluations.
