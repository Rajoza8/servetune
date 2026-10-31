# ServeTune results

Recorded study status: **complete**. Root manifest verified: **True**.

Energy is GPU energy (NVML), not whole-system energy. Observations apply only to the recorded hardware, engine, model revision and frozen workloads.

Indexed trials: 111; verified live observations: 111; synthetic fixtures: 0.


## Fresh confirmation only

The headline table retains every verified live confirmation attempt from the sealed final study, including failures and ineligible configurations. Tuning measurements and synthetic fixtures do not enter it.

| Trial | Config | Load | Status | Eligible | GPU J/token | GPU J/request | p95 latency (s) |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| confirmation-bf16-default-00 | bf16-default | load-3 | pass | True | 0.46854 | 59.9731 | 6.35791 |
| confirmation-fp8-default-00 | fp8-default | load-3 | pass | True | 0.46627 | 59.668 | 3.20837 |
| confirmation-bf16-default-01 | bf16-default | load-3 | pass | True | 0.468353 | 59.9492 | 6.36264 |
| confirmation-fp8-default-01 | fp8-default | load-3 | pass | True | 0.466383 | 59.6827 | 3.20995 |
| confirmation-bf16-default-02 | bf16-default | load-3 | pass | True | 0.468556 | 59.9752 | 6.36751 |
| confirmation-fp8-default-02 | fp8-default | load-3 | pass | True | 0.466332 | 59.6843 | 3.20444 |
| confirmation-bf16-default-03 | bf16-default | load-3 | pass | True | 0.468575 | 59.9776 | 6.35636 |
| confirmation-fp8-default-03 | fp8-default | load-3 | pass | True | 0.466419 | 59.6884 | 3.20455 |
| confirmation-bf16-default-04 | bf16-default | load-3 | pass | True | 0.468431 | 59.9591 | 6.3541 |
| confirmation-fp8-default-04 | fp8-default | load-3 | pass | True | 0.466168 | 59.6545 | 3.20861 |

## Final paired quality

| Config | Correct / 300 | Reference correct | Lost | Gained | Difference (pp) | Within 2 pp tolerance |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| bf16-default | 284 | 284 | 0 | 0 | 0 | True |
| fp8-default | 285 | 284 | 1 | 2 | 0.333333 | True |
| R-winner | 285 | 284 | 1 | 2 | 0.333333 | True |
| S-winner | 285 | 284 | 1 | 2 | 0.333333 | True |

A count-tolerance pass means **within the predeclared 2-percentage-point tolerance** on these fixed items; it is not statistical equivalence or general absence of regression.

## All process evidence

Failed, incomplete, reverted and synthetic trials remain in [trials.csv](trials.csv). [headline.csv](headline.csv) is restricted to confirmation. The [offline dashboard](dashboard.html) supports load/phase/arm filters, trial replay and recorded power traces.

Quantization is not assumed to improve energy or latency. Observed A/B ranges are descriptive; tuning-time screening margins are not significance tests. An agent loss or inconclusive comparison must remain visible.

## Budgets and time

Meta API cap: **$15**; Baseten cap: **$5**. GPU rentals have a separately authorized **$60 cumulative Vast cap**; this report does not infer provider invoices or remaining rental credit from trial time.

| API provider | Accounted USD | Cap USD | Unreconciled USD |
| --- | ---: | ---: | ---: |
| meta | 0.059826 | 15 | 0 |
| baseten | 0 | 5 | 0 |

API amounts are retained token-based estimates and unknown-call reservations, not invoices. Each arm's allocated planning, startup, warmup, measurement, evaluation and failure time must be charged; the other arm's allocation stays paused. See [decisions.csv](decisions.csv) and the retained arm histories.
