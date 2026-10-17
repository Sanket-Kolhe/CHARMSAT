# CHARMSAT reference prototype

Copy this folder into the repo as `reference/`. It is the measured basis for the blueprint and the code the build playbook ports from. Treat it as read-only.

| File | What it is |
|---|---|
| `charmsat_core.py` | Three-stage engine: units → cabinets (CP-SAT, lower bound), cables → CIOCs (CP-SAT per cabinet), slots (exact FFD, CP-SAT fallback); Benders cuts; revision with keep literals; synthetic generator; hardware table |
| `independent_checker.py` | Re-derives every rule from IO rows + allocation rows + rules. Imports nothing from the engine |
| `bench.py` | `python bench.py 1000 5000 10000` → one JSON line per N (cabinets, bounds, violations, determinism, Rev B moves vs from-scratch) |
| `robustness.py` | 40 random rule variants, an adversarial all-defects file, and the live-added AC/DC rule |
| `headroom.py` | `python headroom.py 1000` → Rev A headroom vs Rev B moves trade-off |
| `results/*.jsonl` | The outputs quoted in the blueprint (15 Oct 2026, 2 vCPU sandbox, Python 3.13, OR-Tools 9.15.6755) |

Requirements: `pip install ortools` (Python 3.11+). Runs offline.

Known limits: rule set is a Python dict (the playbook replaces it with the YAML rule language); naming patterns, template writing, MUS explanations and `max_count` rules are not in the prototype.
