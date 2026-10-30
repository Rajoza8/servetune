# Measurement and decision protocol

The study is limited to one physical RTX PRO 6000 Blackwell 96 GB, one pinned
vLLM build, Muse Glimmer revision, and frozen GSM8K math workload. Its objective
is GPU energy measured by NVML's cumulative energy counter. It does not measure
whole-system energy or establish general transfer to other workloads/devices.

## Work and timing

Poisson arrival traces are generated once from a fixed seed, saved and hashed.
The client schedules arrivals independently of inference completion. Fixed
client capacity is recorded; client saturation fails requests instead of
silently reducing offered load. Queue delay is part of TTFT and end-to-end
latency. Every request must complete. The energy window starts at first arrival
and ends after the last completion, including queue drain. Warmup is fixed and
excluded. The study uses the passing 480-second preflight window or longer.

Actual prompt/output usage comes from the serving engine. GPU J/output token
and GPU J/completed request are always shown together. A change exceeding 2%
in total generated tokens is flagged; an energy improvement then requires both
metrics to improve against the shared reference. Failed and saturated loads
remain recorded. A fresh owned engine precedes every measured repeat.

## Quality

The immutable bf16 dev reference is 138/150, measured once in preflight. Every
candidate uses that reference, never the last accepted candidate's quality.
The minimum passing count is 135/150 with no failed evaluation requests.
The scorer and deterministic decoding/prompt policy are preserved byte-for-byte.
Truncations are reported separately. Final confirmation uses 300 separate items,
once per unique selected configuration, with paired gains/losses against the
fresh bf16 default on those same items. A passing result means **within the
predeclared 2-percentage-point tolerance**, not statistical equivalence.

## Search fairness

Random search samples the full finite whitelist with a fixed seed. Spark changes
one knob per proposal and receives only the shared measured start and its own
aggregate history. Neither arm receives the other's search results. Spark does
not see the energy map, A/B results, evaluation answers or held-out items.
Schema rejection happens before any proposed engine command can run.

Both arms use the same dtype, load, space, latency SLO, quality reference and
acceptance rule. Their budgets sum allocated wall-clock intervals. Planning,
model loading, warmup, measurement, quality checks, failed attempts and cleanup
all count. The clock pauses while the other arm owns the GPU. An unfinished
trial at cutoff is recorded and discarded. Acceptance requires a strict median
GPU J/token gain greater than max(2 × observed energy CV, 2%), with all gates
passing. Observed search costs remain separate for each arm.

## Provenance and claims

Each sealed trial saves hardware/engine identity, exact command/config, source
hashes, trace/prompt hashes, raw counter samples, request timings, quality outputs,
and errors. Decisions and proposals are indexed by the controller. Offline replay
checks hashes; synthetic process tests cannot become live evidence. Hashes detect
changes but are not a signature or write-once storage.

Only fresh final confirmation data appear as headline results. Inconclusive,
negative, failed and quality-rejected outcomes are retained. The dashboard and
video must describe those outcomes without replacing them with tuning peaks.

## Prior work

[InferenceBench](https://arxiv.org/abs/2607.20468) found simple hyperparameter
search stronger than its tested agents under matched budgets, motivating an
explicit random-search arm. [AutoTuneBench](https://arxiv.org/abs/2609.18123)
motivates frozen protocols, provenance and honest baselines. ServeTune makes no
novelty or state-of-the-art claim.
