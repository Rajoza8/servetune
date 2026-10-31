# Build record

October 29, 2026, America/New_York: started the standalone ServeTune preflight
harness from the user-approved v4 brief. Work includes frozen public-data
preparation, streamed workload accounting, GPU/runtime probes, owned vLLM
lifecycle, NVML energy capture, noise gating, source-hashed evidence and offline
replay, cumulative API budgets, quality scoring, and allocated arm clocks.

The preflight snapshot records the exact source used for each run. Tests use
offline fixtures. Simulated metrics are explicitly labeled and cannot satisfy
live GPU gates. No energy saving has been established.

At this first milestone the energy-map and controlled agent-vs-random
experiments were not yet implemented. Public repository publication and deployment have not
occurred. No commit was fabricated or dated retroactively;
actual commit history can be added when this work is committed for release.

October 29, 2026, America/New_York: verified the pinned Vast Muse Glimmer wrapper
on a rented RTX PRO 6000 Blackwell. The first live attempt recorded one complete
trace and a 138/150 bf16 dev baseline (zero failed or truncated requests). It
stopped before repeat two because the port precheck rejected TCP TIME_WAIT;
a real-socket regression reproduced that harness defect and a narrow reuse
check fix was implemented. The initial failed attempt remains sealed. The
reference score stays frozen; full measurement gates are pending verification.

October 29, 2026, America/New_York: completed live preflight after preserving the
initial port-guard failure and the 120-second noise failure. Three fresh
480-second arrival-window traces passed: GPU J/token CV 0.6034%, p95 latency
CV 2.2965%. The original 138/150 quality reference was imported without new
quality calls. Online FP8 serving smoke selected CUTLASS FP8 and FlashAttention 2,
reported 32.41 GiB model loading memory, and returned ready. No FP8 energy or
quality benefit is claimed. Offline replay verified the final seal.

October 30, 2026 12:07 AM EDT: implemented the v4 study controller, finite search schema,
history-isolated Spark planner, complete-workload trial runner, equal allocated
arm budgets, numerical quality gates and final confirmation guard. Added a
standalone offline dashboard, CSV/SVG reports, and three-minute video renderer.
A complete synthetic rehearsal produced 237 verified fixture trials and zero
live headline results. Synthetic output does not establish the conditional floor.
The rented GPU was stopped with user approval; a later resume was unavailable
and its queued request was cancelled. Full measurement results are pending a
confirmed GPU allocation. The approved cumulative rental limit is $60 with up
to 35 additional GPU hours; Meta $15 and Baseten $5 remain unchanged.

October 31, 2026, America/New_York: started ServeDoctor, a separate package
(`servedoctor/`) built on ServeTune's engine lifecycle, NVML and workload code.
Implemented the ServeIncidents fault catalog and seeded scenario generator with
sealed answer keys, an open-loop load generator behind a live-adjustable
gateway, once-per-second Prometheus/NVML/client telemetry recording, fault
injectors (traffic surge, long-prompt flood, KV-cache starvation, low batch
limit, small context limit, GPU contention, underutilization, healthy
controls), an observation builder with no look-ahead, four evaluation arms
(threshold rules, Glimmer, Spark, Glimmer→Spark), a separate API ledger
(Meta $50, Baseten $20), scoring, an HTML report, a closed-loop live mode with
verify-or-rollback, and a synthetic rehearsal mode. Tests run offline against a
fake vLLM server. No GPU recording or ServeIncidents result exists yet.
