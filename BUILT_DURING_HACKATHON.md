# Build record

Dates use America/New_York. The result packages retain the exact source
revisions, frozen inputs, measurements and limitations for each study.

**October 29, 2026:** implemented ServeTune's public-data preparation, pinned
vLLM lifecycle, streamed workload accounting, NVML energy measurement, quality
scoring, source-hashed artifacts and offline replay. Live preflight established
a frozen 138/150 BF16 development reference. After preserving the initial port
check and measurement-noise failures, three fresh 480-second traces passed:
GPU J/token CV 0.6034% and p95 latency CV 2.2965%. Online FP8 serving also passed
its startup and completion checks.

**October 30, 2026:** completed the v4 study controller, finite tuning space,
separate random/Spark histories and allocated clocks, quality gates, final
confirmation, dashboard, CSV/SVG reports and demo renderer. The GPU study
completed 111 verified live trials. Neither search arm found an accepted energy
improvement over its shared FP8 starting configuration. Five fresh confirmation
repeats per precision measured 0.471% less GPU energy per output token and
49.54% lower p95 latency for FP8 than BF16, within the declared quality tolerance.
See [the v4 results](results/20261030/README.md).

**October 31–November 1, 2026:** implemented ServeDoctor and ServeIncidents:
seeded serving faults with sealed answers, an adjustable gateway, one-second
telemetry, observations without look-ahead, model and threshold-rule arms,
cost accounting, scoring, reports and a live verify-or-rollback loop. Added
Muse Wonder alongside Spark. Offline tests use a fake vLLM server and explicitly
label synthetic rehearsal data.

**November 1–2, 2026:** recorded and evaluated ServeIncidents v0: a healthy
reference, 8 development incidents, 16 test incidents, six evaluation arms and
12 live repair runs. Rules and Glimmer→Spark each recovered in 5 of 6 live runs;
gateway shedding and the distinct recovery criteria are reported separately.
Development calibration, integration fixes and failed attempts are documented
in [the v0 results](results/servedoctor-20261102/README.md).

**November 2–3, 2026:** built and recorded ServeIncidents-Hard with config noise,
decoy GPU jobs, four compound faults and a predeclared symptom check. The
recording host was calibrated before generation. Of 16 frozen incidents,
`hard-16` could not start because a generated batch setting left insufficient
KV-cache memory; its exclusion preceded validation and scoring. All six arms
were evaluated on the 15 completed incidents, of which 14 passed symptom
validation. No model agent proposed a harmful action, rules stopped a harmless
job in 5 of 6 cases containing decoys, and no arm proposed a safe complete fix
for any compound incident. See [the Hard results](results/servedoctor-hard-20261103/README.md).

**November 3, 2026:** packaged the ServeDoctor submission with a results README,
the static results and live-repair replay page, its reproducible builder and
third-party notices. The earlier ServeTune documentation remains in
[SERVETUNE.md](SERVETUNE.md). Public documentation and packaging changes do not
change the frozen decisions, answer keys or scores.
