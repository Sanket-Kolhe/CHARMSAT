# CHARMSAT — Empirical Benchmark Report
**Project:** IO SIGNAL SUDOKU | CODE APEX 3.0 Hackathon (VIT Pune)  
**Team:** lost_in_the_shine | **Lead:** Prathmesh Vishwakarma  
**Engine:** OR-Tools CP-SAT (3-stage) + Independent Verification Engine  

---

## 1. Measured results (`make bench`, 2026-10-17, commit 4052034)

Machine: 8 CPUs · Python 3.10 · OR-Tools 9.15 · deterministic single-worker
mode. Every figure below was measured by `scripts/bench.py` in that run
(raw: `bench/results.csv`, UI: `bench/results.json`).

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

Reading the table honestly:

- **CHARMSAT: 0 violations at every scale** (independent checker on
  allocation rows), cabinet count equal to the proven lower bound at 1,000
  signals and at most 1 above it at 5,000/10,000. Deterministic re-runs
  matched bit-for-bit in the same run.
- **B0/B1 "negative gaps" are not wins:** they use fewer cabinets by
  breaking rules (hundreds to thousands of checker violations: severed
  cables, mixed A/B trains). Fewer cabinets + violations = illegal packing.
- **Revisions:** keep-literal Rev B moves 2–12% of unchanged signals vs
  92–99% for a from-scratch re-solve, both computed live per run.
- Reproduce: `make bench` (writes `bench/*` with machine/date/commit).

## 2. Method (blueprint §10.6)

Synthetic generator at N ∈ {1k, 5k, 10k} (seed 42, IO mix AI 35 / DI 35 /
DO 20 / AO 10, cable sizes 24/12/6/2, 35% A/B segregated); baselines B0
file-order and B1 grouped-greedy (honest: violations and unplaced counts
reported, moves measured tag-by-tag); from-scratch re-solve baseline for
revisions. Metrics: checker violations, coverage, cabinets, lower bound,
gap, Rev B moves (% of unchanged signals), runtime, determinism hash.

## 3. Reference prototype results (for orientation, NOT repo claims)

The numbers quoted in the blueprint
(`CHARMSAT_v2_Blueprint_and_Playbook.md` §1.2) were produced by
`reference/bench.py` on 15 Oct 2026 (2-vCPU sandbox, Python 3.13,
OR-Tools 9.15). Raw: `reference/results/*.jsonl`.
