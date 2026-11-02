# ServeDoctor GPU rental accounting

Updated: 2026-11-01T21:16:19.264152+00:00 (UTC). Instance: 58690026.

GPU + 150 GB disk while running: $1.375000/hour; retained disk: $0.041667/hour.
Running hours: 2.848502; rental upper estimate: $3.946146.
Network allowance reserved: $2.00; total including reserve: $5.946146 of $40.

Accounting starts at each start request and closes only after an observed stopped state, so startup and shutdown uncertainty are charged conservatively. Disk is charged for the entire retained period, including stops. Network allowance covers model/image download and artifact transfer; provider invoice may differ. Any estimate exceeding the allowance requires stopping and reconciliation.

| Start UTC | Observed stop UTC | Hours upper bound | Reason |
| --- | --- | ---: | --- |
| 2026-11-01T17:42:59.682782+00:00 | 2026-11-01T18:00:58.912439+00:00 | 0.299786 | initial create, including startup |
| 2026-11-01T18:01:28.448365+00:00 | 2026-11-01T18:02:21.574759+00:00 | 0.014757 | retrieve-startup-failure-attempt1 |
| 2026-11-01T18:04:52.673656+00:00 | 2026-11-01T18:11:49.584859+00:00 | 0.115809 | preflight-calibration-attempt2 |
| 2026-11-01T18:13:01.639802+00:00 | 2026-11-01T18:17:52.946023+00:00 | 0.080918 | kv-probe-attempt1 |
| 2026-11-01T18:19:14.982062+00:00 | 2026-11-01T19:19:41.901730+00:00 | 1.007478 | reference-dev-record-attempt1 |
| 2026-11-01T19:21:58.235772+00:00 | 2026-11-01T19:30:38.637070+00:00 | 0.144556 | kv-dev-refinement-attempt1 |
| 2026-11-01T19:33:30.386171+00:00 | 2026-11-01T20:37:14.769205+00:00 | 1.062329 | reference-dev-record-kv2-attempt1 |
| 2026-11-01T20:37:22.927012+00:00 | 2026-11-01T20:41:58.796480+00:00 | 0.076630 | dev-model-evaluation-kv2-attempt1 |
| 2026-11-01T21:02:59.442398+00:00 | 2026-11-01T21:05:16.036211+00:00 | 0.037943 | dev-model-evaluation-api2-attempt1 |
| 2026-11-01T21:10:27.773483+00:00 | 2026-11-01T21:10:57.640063+00:00 | 0.008296 | dev-model-evaluation-api2-attempt2 |

Initial plan: 9 hours × $1.375 = $12.375, plus $2 network/storage buffer = $14.375.
Failures, API mutation outcomes, and stop reasons are retained in session.json and operation-events.jsonl.
