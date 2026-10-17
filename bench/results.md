# CHARMSAT benchmark (2026-10-17, commit 4052034)

| Signals (N) | Engine | Violations | Cabinets / LB | Gap | Rev B moves (ours / scratch) | Runtime (s) |
|---|---|---|---|---|---|---|
| 1,000 | B0 Greedy (File Order) | 116 | 3 / 4 | -1 | - | 0.01 |
| 1,000 | B1 Greedy (Grouped + A/B) | 205 | 3 / 4 | -1 | - | 0.03 |
| 1,000 | **CHARMSAT (3-stage)** | **0** | **4 / 4** | **0** | **24 (2.4%) / 971 (99.1%)** | **0.07** |
| 5,000 | B0 Greedy (File Order) | 618 | 14 / 19 | -5 | - | 0.05 |
| 5,000 | B1 Greedy (Grouped + A/B) | 1176 | 15 / 19 | -4 | - | 0.06 |
| 5,000 | **CHARMSAT (3-stage)** | **0** | **20 / 19** | **1** | **473 (9.7%) / 4641 (94.7%)** | **9.22** |
| 10,000 | B0 Greedy (File Order) | 1197 | 27 / 38 | -11 | - | 0.11 |
| 10,000 | B1 Greedy (Grouped + A/B) | 2498 | 28 / 38 | -10 | - | 0.15 |
| 10,000 | **CHARMSAT (3-stage)** | **0** | **39 / 38** | **1** | **1141 (11.6%) / 8972 (91.6%)** | **8.53** |
