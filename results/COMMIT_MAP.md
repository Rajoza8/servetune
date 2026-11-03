# Commit map

On November 3, 2026, commit metadata on `main` (authorship and message trailers) was normalized. File
contents did not change: each rewritten commit has exactly the same tree hash as the original.
Evidence files written before then (freeze records, manifests, result READMEs) cite the original
commit hashes. This table maps each one to its current commit; `git rev-parse <current>^{tree}`
returns the tree hash shown.

| Original commit | Current commit | Tree | Date | Subject |
| --- | --- | --- | --- | --- |
| `2fff8234a89a04bfe6c52ff43a5cbd8b2088d53f` | `dbe14ccc4753c14b22d9ad4837522c6c4c0259d5` | `b7f13b275468` | 2026-10-31 | Add ServeDoctor agent and ServeIncidents benchmark harness |
| `f8ae40ae179e9260a9ae13e2c8dd8bbc3293389e` | `c7432958746bb65bf3cbffc4538cbdaee25094c5` | `140eebffa688` | 2026-11-01 | Add Muse Wonder arms alongside Spark |
| `a2cf73e23383246b35f96a309b8aa09cc17557fd` | `303018e65bfe29374b06a155ef8ba3be1d6da925` | `36a4d4f3f41c` | 2026-11-01 | Stop ServeDoctor at budget warnings and preserve paid checkpoints |
| `b5c2b506716cb544643096cb89669f389d35f741` | `837bb3f4e9ae8df2d3d75c0cff0288d2794b6400` | `6b7f7f2e7c7e` | 2026-11-01 | Preserve GPU failures and restore failed live engine changes |
| `0bd22ffd7e56750d3c7b52367ddd67539391b780` | `6e555978f84df02e8bc6fb2c47f27423659820bb` | `b9edca886061` | 2026-11-01 | Document v4 offline model cache settings for ServeDoctor |
| `9dd15a898d22ccc50c3c396bd19e873406e66f9a` | `5d1dc43c3ca314671bc3ad4e622d9e85f5b3488c` | `218a1c9baa0c` | 2026-11-01 | Measure contention duty with completed GPU work |
| `d49fad16d8bf7e506f952c2578b0b947a647d914` | `f19654aac8038fa75776bcb20f468c1c55441550` | `e92e9bc1886b` | 2026-11-01 | Calibrate KV fault severities before study generation |
| `ab670ded4bdb0fceb19ebb511c83de53e3ee3545` | `fcd8a2c9cd7edeba29098159d8ad5bf9a6c5754f` | `3de08b33b3dc` | 2026-11-01 | Fit Glimmer evaluation observations and preserve each engine run |
| `aedc7d907df3a82323b208cf7ad627da6ca61064` | `ccdbd7d021a1060ea361b5810b0333c2ac260e95` | `3603883f4eff` | 2026-11-01 | Escalate monitor failures and halt rejected paid requests |
| `1be578f8e73348c53de8117272ba9499c4a954c9` | `a0aa1478132fac418025d7cbaeac13c029bdc9a0` | `4ce4f0b3a613` | 2026-11-01 | Tune surge threshold on dev to avoid harmful batch misdiagnosis |
| `ea9c29434edc971ab1e410f230b11cb57fddfe58` | `8bf86972f360324f57aeac5238eb3d85acc4a5a4` | `4150b7e8be99` | 2026-11-01 | Strengthen KV incidents using development pressure probes |
| `d95f4a6c091e2373565e6eac73069991324772c8` | `728d80a2c9a28d9fcdba471825297993ef079d06` | `15c60671c191` | 2026-11-01 | Fail fast on invalid ServeDoctor API credentials |
| `092a5ca6ba98360b07c89d318f15e6abf3a87435` | `7a9b74b13f609be5211067d0f5a62044ac64116b` | `10c9608bc14f` | 2026-11-01 | test: remove context recovery fixture timing race |
| `cf0d6cbfbe405dd3377708652ad0921b968908ca` | `1f1236085dd98fde5829765cb1d1ed1b35bd4623` | `a61d3b4be9b3` | 2026-11-01 | fix: clean up failures during live initialization |
| `3fea48a84cec07231f3a658f57ccc7b125eda8ae` | `e49cdebb9f3cd523c6f4cbe4d3f478ae5e08937f` | `4c4888cc53d1` | 2026-11-01 | calibrate replacement GPU KV pressure before study |
| `a0b4deb6e9545b9d21fde472ad4686645b083bc6` | `ba4761d4e3d77e68e57ab9ed9ae3ed28f4a21754` | `fbd3c8289005` | 2026-11-01 | support explicit Meta TLS CONNECT transport for GPU studies |
| `da5596d9595214bd912bf15788d82cf58f5547ea` | `e5e223f054f4cb1255746e475bcab6915cbfcb86` | `97b2b3fdc932` | 2026-11-01 | Preserve background collector failures as failed recordings |
| `36f5d2a1be591a53dc8f45a05ee361c7660f039b` | `8b021559925753638be9c2bc864ac103bbe15a12` | `af8e3ebb26b9` | 2026-11-02 | Publish frozen ServeDoctor benchmark and live recovery results |
| `d3fe20a07ce9c687e75956200b655c5913021d49` | `c595fb83ad9ad8fce4606962d964e2d107e4c55c` | `b85daaaf7e32` | 2026-11-02 | Add ServeIncidents-Hard: compound faults, decoys and config noise |
| `973bdd9ef96b4087845fc83f3e4ebcaa2ad3a4d4` | `f8c90fd5001a5d5e3a42fc9f22c76f96b238a1d9` | `3454021b8383` | 2026-11-02 | Calibrate Hard KV values for replacement Blackwell host |
| `4b0add12be36cef0d0776607f683310b1641b0f7` | `716de22db946c2e90e7aed4152bdea00906e68a4` | `83f63ae97410` | 2026-11-02 | Calibrate Hard KV values for the final recording host |
| `95731081baaf3c44f60eb10671ed60c8aa1e0aaf` | `960186c3dd00cf285297ea304c308e46e1920d42` | `0bb881dc23c9` | 2026-11-02 | Package ServeIncidents-Hard results with the hard-16 exclusion |
| `b9194e2d3e67f26e9c364172709bb6a20fe68460` | `76f741aa0308b7fa2e4e3f57bfcf5fdff02a7f69` | `eaa35adb8060` | 2026-11-03 | Package the ServeDoctor submission: README, results page, notices |
| `8c60bdcee416d538d482fc1bc9c8dd08e88daeda` | `aaac0e19905a471f61355b1fde6cb606ef824387` | `285c40631d22` | 2026-11-03 | Drop the GPU-provider references from docs and remove a copied CLI |
