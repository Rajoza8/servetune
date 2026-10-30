# ServeTune

ServeTune measures GPU energy for an open-weight Meta model under a frozen
request trace. The implementation includes preflight, the v4 experiment
controller, quality gates, isolated arm budgets, cumulative API accounting,
sealed evidence, offline replay, and a dashboard. The GPU study produces the
results; implementing a controller does not establish an energy saving or an
agent advantage.

This is a standalone Python 3.11+ project inside the existing workspace. It does
not import or modify Verifier Forge. Its ledger is separate. The accepted scope
is preserved verbatim in `BUILD_BRIEF_V4.txt`.

## On your Mac

The core uses the Python standard library. Import, simulation, replay, and tests
do not install CUDA/PyTorch, download model weights, or contact model providers.
Run these commands from this directory:

```sh
python3 -m servetune --help
python3 -m unittest discover -s tests -q
python3 -m servetune preflight --simulate --out runs/mac-smoke
python3 -m servetune replay runs/mac-smoke
python3 -m servetune doctor
```

`doctor` only reads runtime/GPU information. On a Mac it returns exit code 2 and
an explicit missing-NVIDIA blocker. Simulation returns exit code 0, but records
`mode=synthetic_fixture`, `live_preflight_passed=false`, and `floor_built=false`.
Its values never qualify as hardware or model-performance evidence.

Each preflight needs a fresh output path. It writes a readable `preflight.md`,
structured `preflight.json`, flushed `events.jsonl`, exact configuration, source
snapshot, and SHA-256 manifest. Replay verifies every saved file before showing
the report. Artifacts are exclusively created; hashes detect later changes,
although ordinary filesystem files are not write-once storage.

## Prepare public data

This explicit command downloads a few MB of licensed public data, not weights:

```sh
python3 -m servetune prepare-data --out data/gsm8k
```

If a python.org macOS installation reports a certificate verification error,
configure its trusted CA bundle. On this Mac, the system bundle works without
changing the machine or disabling TLS verification:
`SSL_CERT_FILE=/etc/ssl/cert.pem python3 -m servetune prepare-data --out data/gsm8k`.

It resolves the official [GSM8K repository](https://github.com/openai/grade-school-math)
to an exact commit and retains its MIT license, raw files, selected indices, and
hashes. A fixed seed chooses 12 performance-calibration prompts, 150 dev items,
and 300 final items with disjoint questions. The preflight workload is explicitly
**math-only calibration**, not a representative chat/code/long-context mix.
Broader workloads and saturation sweeps belong to the energy-map milestone.

Final items are checked locally for split integrity and hashed. Preflight never
sends them to the model or scores them. The final evaluation remains reserved
for the later confirmation; preparing data does not run it.

## On the NVIDIA host

You can execute the commands yourself; SSH access for the assistant is optional.
A Vast instance can also run the same bundle. A rental requires a separate
user-selected budget; the API caps below do not authorize GPU rental spending.

Required: exclusive measurement access to one RTX PRO 6000 Blackwell 96 GB,
compatible NVIDIA drivers and Glimmer-capable vLLM build, readable NVML energy
telemetry, and disk space for approximately 60 GB of bf16 weights plus runtime,
cache, and artifacts. No power-limit changes, clock locking, driver changes, or
root privileges are used. Install vLLM following the pinned Glimmer-compatible
environment in [Meta's deployment guide](https://dev.meta.ai/docs/muse-glimmer/deploy).
The harness records that installed version; it does not silently install a
potentially incompatible engine. If using a container, run the harness inside
the same container/environment as vLLM, with NVIDIA/NVML visible.

```sh
python3 -m pip install -e '.[gpu]'
python3 -m servetune doctor
python3 -m servetune prepare-data --out data/gsm8k
python3 -m servetune preflight --data-dir data/gsm8k \
  --model-revision YOUR_EXACT_40_CHARACTER_HUB_COMMIT \
  --max-hours 6 \
  --out runs/gpu-preflight
```

Use the actual immutable commit from the Glimmer model repository, not `main`.
Set `--max-hours` to your available after-hours allocation. The deadline reserves
30 seconds for cleanup, bounds startup/request timeouts to remaining time, and
refuses a new phase that cannot fit. Partial work remains recorded as incomplete;
it cannot pass a gate. Leave additional time before the machine's business-use
handoff for a human check that the owned server has exited. This is an application
deadline, not a host administrator's hard resource-revocation mechanism.

After-hours/weekend sessions can use separate output directories on the same
GPU. Preserve all evidence and the single API ledger. An interrupted preflight
remeasures all three performance repeats in a fresh output directory. It never
merges partial noise repeats or selects a replacement quality score.

If a run completed its 150-item bf16 development reference before a later
operational failure, preserve that once-measured reference explicitly:

```sh
python3 -m servetune preflight \
  --data-dir data/gsm8k-20261029 \
  --model-revision YOUR_EXACT_40_CHARACTER_HUB_COMMIT \
  --dev-baseline-evidence runs/original-sealed-preflight \
  --spark-evidence runs/spark-preflight \
  --max-hours 2 \
  --out runs/fresh-preflight-with-frozen-reference
```

Reference import verifies the original seal, all 150 per-item outcomes and
aggregate counts, frozen data/scorer, model/tokenizer revisions, default-bf16
command, physical GPU UUID, driver, and vLLM version. Data paths may relocate
only when all recorded hashes remain identical. Quality and request source
must be unchanged. V4's P4 calibration may increase `trace.duration_s` while
reusing that same quality reference; duration decreases and every other trace,
measurement, engine, or quality setting change are rejected. The original and
current performance-window lengths and the calibration reason are recorded in
the import origin. All three performance repeats still run fresh at the new
duration. Engine source may differ only in the port-availability
probe, which is checked structurally. The complete sealed original and origin
hashes are copied into the new evidence directory. A source run's later failed
performance restart does not invalidate its completed reference. Import never
generates a new quality sample, changes its score, or imports performance
repeats; the final evaluation remains untouched.

Live mode explicitly starts vLLM and may download the pinned weights into its
normal Hugging Face cache. It refuses existing servers rather than attaching to
or terminating them. Only its own verified process group is stopped. Model and
tokenizer revisions are pinned, and GPU UUID selection links serving and NVML.

`configs/preflight.example.json` is the complete schema. It uses the engine's
batching/memory defaults under a fixed 4096-token context cap and disabled prefix
cache, rather than presenting a hand-configured scheduler as engine defaults.
Values for the four later tuning knobs are ignored while
`use_engine_defaults=true`. Backend and footprint evidence must be present in
startup logs; otherwise P1 fails explicitly rather than inventing a backend.

Preflight executes:

- **P1:** hardware/runtime identity, pinned bf16 startup, streamed completion,
  actual usage, backend/footprint logs, owned-process cleanup.
- **P2:** idle/load cumulative-energy readings, timestamps, GPU UUID, counter
  updates and a conservative observed window-boundary granularity check.
- **P4:** three identical open-loop traces, fresh engine/warmup for each,
  complete-workload energy including queue drain, actual tokens and J/request,
  J/token and p95 latency CV below 3%. Failed requests fail the run.
- **Dev baseline:** 150 exact-match items once on the bf16 reference; failures
  block baseline readiness. No candidate or final-eval improvement is claimed.
- **P1b:** optional online FP8 startup/completion and backend evidence after
  measurement gates pass. It does not demonstrate an FP8 quality or energy gain.
- **P3:** explicit, separately budgeted Meta connectivity/schema check below.

The trace lasts at least 120 seconds of scheduled arrivals, at a conservative
calibration rate. It is not a saturation test. Energy covers from its first
arrival through all requests completing. TTFT and end-to-end latency include
client dispatch lag/queueing from the scheduled arrival. Reasoning tokens count
in engine-reported generated tokens. Missing usage or incomplete SSE fails.
Runs store raw energy and per-request timing records alongside summaries.
Measured workload and quality generation are fixed to greedy decoding and
`reasoning_strength=low`. Serving-only smoke checks use the model's sampled
configuration (temperature 1) and 2048-token headroom before requiring a normal,
nonempty final response. Smoke checks are excluded from energy measurements and
quality scoring. Both paths use `--generation-config auto` to retain the pinned
checkpoint's published stop tokens; explicit request settings freeze measured
decoding. These policies stay fixed across dtypes/configurations.
[Meta prompting guide](https://dev.meta.ai/docs/muse-glimmer/prompting)

The cumulative NVML counter is the passable energy source in this initial
version. Explicit averaged-power fallback can produce diagnostics, but does not
pass P2; automatic source substitution would change the declared objective.
Granularity bounds describe observed counter update steps, not absolute sensor
accuracy. NVML power samples may represent one-second averages, so repeated
polls are not independent readings. [NVIDIA NVML documentation](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html)

If P1, P2 or P4 fails, later experiments stop. `measurement_prerequisites_passed`
only covers those gates. `live_preflight_passed` also requires P3 and the valid
dev baseline. Preflight never sets `floor_built=true`: the floor still requires
an actual energy map and replayable evidence, plus the FP8 study if applicable.

## API spending

Initialize exactly one persistent ledger on the host where paid calls run:

```sh
python3 -m servetune init
python3 -m servetune budget
```

`runs/ledger.json` caps ServeTune at **Meta $15 / Baseten $5**, separately from
Verifier Forge. It refuses reinitialization. Preserve and transfer this ledger
if moving the project between machines; never initialize a second live allowance.
Public-data fetching, simulation and GPU serving do not make provider API calls.

For one P3 request, export `MODEL_API_KEY` (or `META_API_KEY`) in the environment
and run:

```sh
python3 -m servetune spark-check --out runs/spark-preflight
python3 -m servetune budget
```

Alternatively, `preflight --with-spark ...` checks P3 once after measurement
prerequisites pass. Neither command retries. A reservation is durably recorded
before dispatch; failed/unknown attempts retain the full reservation. Valid
reported prompt/completion usage is reconciled, including charges from invalid
or truncated outputs. Reasoning is included in completion counts. Accounting
uses published standard token rates without cache discounts and is an estimate,
not an invoice. Overruns are retained and block paid work. Warnings appear at
50%; reservations that exceed either hard cap are refused. No Baseten calls or
deployments are implemented.

A successful standalone P3 can be reused in a **new** GPU preflight without a
second paid request:

```sh
python3 -m servetune preflight \
  --data-dir data/gsm8k-20261029 \
  --model-revision YOUR_EXACT_40_CHARACTER_HUB_COMMIT \
  --max-hours 2 \
  --spark-evidence runs/spark-preflight \
  --out runs/gpu-preflight-with-saved-spark
```

`--spark-evidence` and `--with-spark` are mutually exclusive. Import verifies the
exact current model/request/schema/fixed baseline, proposal, usage and cost,
settled reservation, and all three evidence-file hashes against the same
cumulative ledger. It copies the verified files before sealing the new run,
records their origin, and sets `paid_calls_this_run=0`. It never modifies an
existing sealed preflight. Move the canonical ledger and P3 directory together
when changing hosts; a fresh allowance cannot authorize imported evidence.

New successful P3 checks bind their file hashes to the ledger automatically.
Legacy evidence with no bound hashes is refused by import. For a directory the
owner has independently reviewed and knows came from their own earlier call,
`planner.attest_spark_evidence(ledger_path, evidence_dir)` explicitly records a
one-time local attestation after protocol/usage/ledger validation. This does not
prove an otherwise unrecorded model response, and import never auto-attests.

`.env` files are never loaded automatically. Keys stay out of artifacts and local
engine environment. P3 saves only the non-secret request, allowlisted usage,
validated/redacted proposal, and result. Official model/endpoint/rates were checked
October 29, 2026: [Meta Chat Completions](https://dev.meta.ai/docs/protocols/chat-completions),
[Meta pricing](https://dev.meta.ai/docs/pricing-rate-limits).

## The two v4 clarifications

`timing.ArmClock` accumulates allocated wall-clock intervals. Each arm's planning,
load, warmup, measurements, quality checks, failures, and unfinished trials count
while its clock runs. Pause it while the other arm runs. Search orchestration is
not implemented yet; the tested clock is ready for it.

`quality.evaluate_gate` uses exact item counts and the same fixed bf16 reference:
150 dev items with at most 3 fewer correct; 300 final items with at most 6 fewer.
Any request failure fails a candidate. Small fixtures cannot qualify for these
gates. Results say **within the predeclared 2-percentage-point tolerance** and
report exact paired losses/gains; they make no statistical equivalence claim.
The scorer extracts explicit `####`/boxed answers, otherwise the final line;
truncation requires an explicit answer marker. Unicode/case/whitespace/plain
decimal normalization is fixed, hashed, and never evaluates expressions.

## Transfer to a GPU host

```sh
python3 -m servetune bundle --out reports/servetune-source.tar.gz
```

The archive contains code, config, tests, and documentation, without credentials,
weights, prepared datasets, or run ledgers. Extract on the target host, enter the
`servetune` directory, then use the commands above. If paid checks have already
run elsewhere, transfer the existing ledger separately before any paid command.
Bring the full preflight run directory back for offline replay/inspection.

For a copy-and-run after-hours entry point on the GPU host (after preparing its
Python/vLLM environment):

```sh
SERVETUNE_MODEL_REVISION=YOUR_EXACT_40_CHARACTER_HUB_COMMIT \
SERVETUNE_MAX_HOURS=6 \
bash scripts/run-preflight.sh runs/after-hours-1
```

The script probes the GPU, prepares the small public dataset if absent, runs the
bounded preflight, and exports `runs/after-hours-1.tar.gz` for you to bring back.
It performs no package installations or paid API calls. P3 remains a separate
explicit check; invoke `preflight --spark-evidence ...` directly to import a
verified prior check. Otherwise successful hardware measurements may still return
exit code 2 with P3 outstanding. Completed and failed preflight reports are both
exported. An interrupted process without a sealed manifest requires inspection
and a fresh run. You can also export manually:

```sh
python3 -m servetune export-run runs/gpu-preflight --out reports/gpu-results.tar.gz
```

Existing prior work is acknowledged in the brief: [InferenceBench](https://arxiv.org/abs/2607.20468)
and [AutoTuneBench](https://arxiv.org/abs/2609.18123). No novelty, whole-system
energy, or general speedup claim is made.

## Full v4 study

`configs/study-v4.json` declares the finite knob space, pilot rates, 480-second
comparison windows, three repeats per map point, six hours per tuning arm,
15-second p95 end-to-end SLO, and five fresh confirmation repeats. The numerical
quality policy remains the original hashed 150/300-item, minus-3/minus-6 gate.
The map uses three load levels, both supported dtypes, and default / 64 sequence
settings. Actual defaults are read from the owned server before workloads freeze.
For the pinned vLLM build on this 96 GB GPU, the source-derived defaults are
1024 sequences, 8192 batched tokens, chunked prefill enabled, and 0.92 GPU memory
utilization; the runner must still observe those values on the live server.
The study enables the owned server's loopback development introspection route
before startup, records that setting, and retains only the four runtime scalars.
It does not save the endpoint's environment diagnostic payload.

For a complete software rehearsal on your Mac, use a fresh directory:

```sh
python3 -m servetune study-init --simulate --out runs/study-fixture
python3 -m servetune study-run runs/study-fixture --max-hours 1
python3 -m servetune study-report runs/study-fixture --out reports/study-fixture
python3 -m servetune study-replay runs/study-fixture
```

Synthetic records exercise the controller but cannot establish a floor, headline
measurement, quality improvement, or energy saving. They never call a provider.

On the same physical GPU as the passing preflight:

```sh
python3 -m servetune study-init \
  --preflight runs/live-preflight-20261029-3 \
  --data-dir data/gsm8k-20261029 \
  --config configs/study-v4.json --out runs/full-v4-20261030
python3 -m servetune study-run runs/full-v4-20261030 --max-hours REMAINING_APPROVED_HOURS
python3 -m servetune study-report runs/full-v4-20261030 --out reports/full-v4-20261030
python3 -m servetune study-replay runs/full-v4-20261030
```

Set `MODEL_API_KEY` or `META_API_KEY` only in the controller environment for Spark.
The owned inference subprocess strips provider keys. `study-run` uses the same
single ServeTune ledger; copying a session never resets its spending history.
The CLI time bound controls experiment execution and cleanup; a separately
authorized rental guard controls Vast billing and lifecycle. Never infer rental
authorization from a CLI option. Baseten has no planned use.

The controller performs calibration, freezes and hashes its comparison traces,
then runs the map, alternating bf16/FP8 A/B, isolated random/Spark search, and
fresh final confirmation. Every performance repeat starts a fresh engine with
the same warmup. Failed and saturated loads stay in the data. Every new tuning
candidate has the same 150-item dev gate against the once-measured bf16 reference.
Planner waiting, loads, warmup, quality, failures and cleanup count against its
arm; the other arm's interval is paused. Both arms receive the same declared
budget, reduced equally if needed to preserve nine hours for final confirmation.

The final 300 items are claimed once per unique selected configuration, after
tuning finishes. Identical winners may share a single measured configuration;
aliases are disclosed. Failed or interrupted final checks are retained and
cannot be silently rerun. Only fresh confirmation rows enter the headline table.
Reports include all raw trials, decision history, paired quality counts, Pareto
charts, length-drift flags, and an offline HTML dashboard. Outputs are outside
the sealed study directory so report generation cannot invalidate evidence.

`study-status` reads saved progress without a GPU or API key. A stopped session
can resume at phase boundaries on the same GPU with its source, data, ledger and
sealed trials intact. A different GPU requires a fresh preflight/reference and
new comparison study; results are never merged across machines.

With the optional media dependencies installed, render the three-minute demo
from verified results without a GPU or provider key:

```sh
python3 -m pip install -e '.[media]'
python3 -m servetune study-demo runs/full-v4-20261030 --out reports/demo
```

The renderer writes a storyboard, narration text and captions even when an
encoder is unavailable. It uses only fresh eligible confirmation data for
headlines. Synthetic/incomplete process demos carry a persistent banner.
An optional local narration file can be supplied using `--audio`.
