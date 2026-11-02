# ServeDoctor GPU rental accounting

Updated: 2026-11-02T09:12:35.275208+00:00 (UTC). Instance: 58716527.

GPU + 150 GB disk while running: $1.479000/hour; retained disk: $0.041667/hour.
Running hours: 14.302195; rental upper estimate: $20.897474.
Aggregate network allowance: $4.00; slack reserve: $1.00; total: $25.897474 of $40.

Accounting starts at each start request and closes only after an observed stopped state, so startup and shutdown uncertainty are charged conservatively. Disk is charged for the entire retained period, including stops. Network allowance covers model/image download and artifact transfer; provider invoice may differ. Any estimate exceeding the allowance requires stopping and reconciliation.

| Start UTC | Observed stop UTC | Hours upper bound | Reason |
| --- | --- | ---: | --- |
| 2026-11-01T17:42:59.682782+00:00 | 2026-11-01T18:00:58.912439+00:00 | 0.299786 | instance 58690026: initial create, including startup |
| 2026-11-01T18:01:28.448365+00:00 | 2026-11-01T18:02:21.574759+00:00 | 0.014757 | instance 58690026: retrieve-startup-failure-attempt1 |
| 2026-11-01T18:04:52.673656+00:00 | 2026-11-01T18:11:49.584859+00:00 | 0.115809 | instance 58690026: preflight-calibration-attempt2 |
| 2026-11-01T18:13:01.639802+00:00 | 2026-11-01T18:17:52.946023+00:00 | 0.080918 | instance 58690026: kv-probe-attempt1 |
| 2026-11-01T18:19:14.982062+00:00 | 2026-11-01T19:19:41.901730+00:00 | 1.007478 | instance 58690026: reference-dev-record-attempt1 |
| 2026-11-01T19:21:58.235772+00:00 | 2026-11-01T19:30:38.637070+00:00 | 0.144556 | instance 58690026: kv-dev-refinement-attempt1 |
| 2026-11-01T19:33:30.386171+00:00 | 2026-11-01T20:37:14.769205+00:00 | 1.062329 | instance 58690026: reference-dev-record-kv2-attempt1 |
| 2026-11-01T20:37:22.927012+00:00 | 2026-11-01T20:41:58.796480+00:00 | 0.076630 | instance 58690026: dev-model-evaluation-kv2-attempt1 |
| 2026-11-01T21:02:59.442398+00:00 | 2026-11-01T21:05:16.036211+00:00 | 0.037943 | instance 58690026: dev-model-evaluation-api2-attempt1 |
| 2026-11-01T21:10:27.773483+00:00 | 2026-11-01T21:10:57.640063+00:00 | 0.008296 | instance 58690026: dev-model-evaluation-api2-attempt2 |
| 2026-11-01T21:37:51.304204+00:00 | 2026-11-01T21:43:44.143760+00:00 | 0.098011 | instance 58716527: approved replacement create, including startup |
| 2026-11-01T21:45:50.194702+00:00 | 2026-11-01T21:48:49.170859+00:00 | 0.049716 | instance 58716527: Resume bootstrap after retained host-key comment parsing failure |
| 2026-11-01T21:50:40.986795+00:00 | 2026-11-01T21:54:44.639195+00:00 | 0.067681 | instance 58716527: Resume bootstrap after retained host-key comment parsing failure |
| 2026-11-01T21:58:17.447547+00:00 | 2026-11-02T09:12:35.273595+00:00 | 11.238285 | instance 58716527: Resume bootstrap after retained host-key comment parsing failure |

Initial plan: 9 hours × $1.375 = $12.375, plus $2 network/storage buffer = $14.375.
Failures, API mutation outcomes, and stop reasons are retained in session.json and operation-events.jsonl.
