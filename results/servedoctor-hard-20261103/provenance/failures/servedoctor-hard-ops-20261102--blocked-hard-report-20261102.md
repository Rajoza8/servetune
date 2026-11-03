# ServeIncidents-Hard: blocked frozen attempt

The frozen 16-incident study cannot currently be completed. Reference and Hard incidents `hard-01` through `hard-15` completed and were preserved byte-for-byte. The final incident, `hard-16`, failed before its workload started. No validity file has been written and no arm has been evaluated. Both requested scoreboards are unavailable.

The GPU rental `58866756` is confirmed stopped, with no pending or queued start. The recording worker had exited before the controller was deliberately interrupted at 22:53:13 UTC on November 2. Cached models and remote evidence remain on the stopped rental; disk retention costs about $0.0833/hour.

The failing engine uses the frozen `gpu_memory_utilization=0.61632`, `max_num_batched_tokens=12288`, `max_num_seqs=64`, and `max_model_len=4096`. vLLM reported **available KV cache memory: -0.54 GiB** and exited with **No available memory for the cache blocks**. After cleanup, GPU memory usage was 2 MiB and no compute process remained. This provides no basis for a retry attributed to leftover GPU memory.

The standalone calibration used an 8,192-token batch. I did not catch the interaction with the incident's 12,288-token batch before freezing the study. Increasing the utilization or reducing that batch setting would change frozen experimental inputs and potentially the resulting observations and decisions. No such change has been made.

The integrity gate requires all 17 recordings and exactly 16 Hard validity verdicts. Native validation would silently skip the missing incident and permanently write only 15 verdicts; therefore it has not been run. Bypassing completeness checks or evaluating a 15-case subset would require an explicit protocol amendment. A new configuration is also outside the current freeze authorization.

Source commit: `4b0add12be36cef0d0776607f683310b1641b0f7`.

Config SHA256: `0cc70e7ec4cbb0b26c6e13a4b9311dedf6dd05a862d9c0d9d2934ec25a017014`.

Experiment freeze SHA256: `868fa1c8c8be1bba186937839bdeba0bebeaab7f95623c181a72f42ba0120a68`.

Answer-key commitment: `fb168177884005df77a94cbb75e6d52946a26ccfc3675db82820bb9105eaadc0`.

Scenario commitment: `bbd1f792878602f6472e56a5795f9f257882ad541b3184ce38af00588c4d3f20`.

Before generation, the new host was calibrated to 6 RPS and its two KV utilizations were set to 0.61632 and 0.61520 with documented evidence. Prompts, rule thresholds, scoring rules, answer keys and Hard incident specifications remain unchanged. Protected ServeTune v4 sources and results remain unchanged.

Conservative GPU accounting is approximately **$37.26 / $40**, including v0, all Hard rental attempts and reserves. Hard rental time is **3.757473 hours**, approximately **18.059668 hours including v0**. The unused 1.3-hour forecast is not incurred rental time. The exact status and cost snapshot is in `blocked-hard-cost-and-status-20261102.json`.

The existing ledger is unchanged: Meta **$12.255891 / $50**, Baseten **$0 / $20**, 443 entries, no warnings. No Hard paid calls occurred. No ledger entry or cap was edited or reset.

The completed recordings and failed engine evidence are preserved in `blocked-hard-study-attempt1/latest/study/`. The last recording archive and its manifest were independently hash-verified, including every extracted file. First-batch ownership proofs were preserved separately. Neither the canonical study location nor any answer key was overwritten. Earlier failures and configuration changes are indexed in `hard-failure-index-draft.json`.

Decision needed: retain this as an incomplete frozen study and use v0, or explicitly authorize a separately labeled amended analysis. Any amended plan must preserve this original attempt, disclose the failed incident and stay within an agreed budget. No further GPU work or model calls will run under the current authorization.
