# ServeDoctor GPU rental accounting

Updated: 2026-11-02T09:16:22.536935+00:00 (UTC). Instance: 58716527.

GPU + 150 GB disk while running: $1.479000/hour; retained disk: $0.041667/hour.
Running hours: 14.302195; rental upper estimate: $20.900104.
Aggregate network allowance: $4.00; slack reserve: $1.00; total: $25.900104 of $40.

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


## ServeIncidents-Hard rental accounting

Prior v0 fixed upper: $25.900104435435; proof SHA256 9c28a7d7b972a89cc9e25f079db45310066afacd4e7d3bd300c4ed87894483de.

Hard instance: 58866756; as of UTC 2026-11-03T01:39:37.395298+00:00.

{
  "prior_v0_usd_upper": 25.90010443543525,
  "hard_running_hours": 3.806694845689668,
  "hard_compute_usd_upper": 5.9761605365664865,
  "hard_disk_usd_upper": 0.6761263185951076,
  "current_host_cost": {
    "running_hours": 2.7350119388103487,
    "compute_usd_upper": 4.157218146991729,
    "disk_usd_upper": 0.5283381860399687
  },
  "prior_hard_host_cost": {
    "running_hours": 1.071682906879319,
    "compute_usd_upper": 1.8189423895747572,
    "disk_usd_upper": 0.1477881325551389
  },
  "new_network_reserve_usd": 4.0,
  "new_slack_reserve_usd": 1.0,
  "total_usd_upper": 37.552391290596844,
  "remaining_gpu_hours": 1.469184076918496,
  "forecast_usd_upper": 39.90798309392283,
  "shutdown_margin_usd": 0.04008333333333333
}

Startup/shutdown uncertainty is charged until GET confirms stopped; retained disk continues until GET confirms deletion.


## Authorized inference-only rental ($43 total cap)

{
  "prior_v0_and_five_hard_hosts_usd_upper": 37.552391290596844,
  "inference_host_cost": {
    "running_hours": 1.5619995722505782,
    "compute_usd_upper": 2.317590832000591,
    "disk_usd_upper": 0.15957029316988253
  },
  "total_usd_upper": 40.02955241576732,
  "remaining_gpu_hours": 0.7021876491440667,
  "forecast_usd_upper": 41.120174668247905,
  "shutdown_margin_usd": 0.038829444444444444,
  "total_cap_usd": 43.0,
  "network_and_slack_reserved_once": true
}
