"""One-command benchmark (P5-1). Every number printed is measured in this run.

Usage: python scripts/bench.py [1000 ...]   (default: 1000 5000 10000)
Writes bench/results.csv, bench/results.md (slide table),
bench/results.json (Benchmarks screen), bench/meta.json (machine/date/commit).
"""
import csv
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.models.rules import RuleSetConfig  # noqa: E402
from app.engine.generator import SyntheticGenerator  # noqa: E402
from app.engine.validator import DataValidator  # noqa: E402
from app.engine.baselines import BaselineEngine  # noqa: E402
from app.engine.solve.engine import solve_allocation, solve_revision  # noqa: E402
from app.engine.solve.bridge import rules_to_ref, to_core_signals  # noqa: E402
from app.engine.hardware import HW_TABLE  # noqa: E402
from app.engine.io.template_writer import rows_from_allocations  # noqa: E402
import checker.check as checker_pkg  # noqa: E402
import ortools  # noqa: E402


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:12]


def _check_alloc(signals, allocations, sizes, rules):
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "",
                "seg": s.seg or ""} for s in signals]
    rows = rows_from_allocations(allocations)
    found = checker_pkg.check(io_rows, rows, rules_to_ref(rules), HW_TABLE, sizes)
    return sum(1 for v in found if v["status"] == "violation")


def run(n, seed=42):
    rules = RuleSetConfig()
    validator = DataValidator()
    baselines = BaselineEngine(rules)
    gen = SyntheticGenerator(seed=seed)
    sig_a, ci = gen.generate_dataset(n_signals=n)
    sizes_a = {c["cable_id"]: c["size"] for c in ci}
    valid_a, tqs_a, ledger_a = validator.validate(sig_a, sizes_a)

    t = time.time()
    res_a, prev_a, raw_a = solve_allocation(valid_a, sizes_a, rules)
    wall_a = time.time() - t
    viol_a = _check_alloc(valid_a, res_a.allocations, sizes_a, rules)

    res_a2, _, _ = solve_allocation(valid_a, sizes_a, rules)
    deterministic = (_digest([a.model_dump() for a in res_a.allocations]) ==
                     _digest([a.model_dump() for a in res_a2.allocations]))

    t = time.time()
    b1 = baselines.run_b1_grouped_ab(valid_a, sizes_a)
    wall_b1 = time.time() - t
    t = time.time()
    b0 = baselines.run_b0_file_order(valid_a, sizes_a)
    wall_b0 = time.time() - t
    viol_b0 = _check_alloc(valid_a, b0.allocations, sizes_a, rules)
    viol_b1 = _check_alloc(valid_a, b1.allocations, sizes_a, rules)

    sig_b, meta = gen.generate_revision_b(sig_a, cable_sizes=sizes_a)
    valid_b, _, _ = validator.validate(sig_b, meta["cable_sizes"])
    t = time.time()
    res_b, _, _ = solve_revision(valid_b, meta["cable_sizes"], rules, prev_a,
                                 valid_a, raw_a.get("rows", []),
                                 to_core_signals(valid_a))
    wall_b = time.time() - t
    viol_b = _check_alloc(valid_b, res_b.allocations, meta["cable_sizes"], rules)
    rs = res_b.rev_summary
    lb = raw_a.get("lower_bounds", {}).get("best", 0)
    return {
        "N": n, "seed": seed,
        "revA_cabinets": res_a.cabinets_used, "LB": lb,
        "gap": res_a.cabinets_used - lb, "status": res_a.solver_status,
        "revA_violations": viol_a, "tqs": len(res_a.tqs) + len(tqs_a),
        "coverage": res_a.coverage_pct if hasattr(res_a, "coverage_pct") else 100.0,
        "deterministic": deterministic,
        "revA_wall_s": round(wall_a, 2),
        "B0_cabinets": b0.cabinets_used, "B0_violations": viol_b0,
        "B0_wall_s": round(wall_b0, 2),
        "B1_cabinets": b1.cabinets_used, "B1_violations": viol_b1,
        "B1_wall_s": round(wall_b1, 2),
        "B1_unplaced_tqs": len(b1.tqs),
        "revB_cabinets": res_b.cabinets_used, "revB_violations": viol_b,
        "revB_wall_s": round(wall_b, 2),
        "moves_ours": rs.moves_ours if rs else 0,
        "moves_scratch": rs.moves_from_scratch if rs else 0,
        "unchanged": (rs.unchanged_count + rs.moves_ours) if rs else 0,
    }


def _commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main(ns):
    import os
    results = [run(n) for n in ns]
    meta = {"machine": platform.node(), "platform": platform.platform(),
            "cpu_count": os.cpu_count(), "python": platform.python_version(),
            "ortools": ortools.__version__ if hasattr(ortools, "__version__") else "?",
            "commit": _commit(), "date": datetime.now(timezone.utc).isoformat()}
    bench = ROOT / "bench"
    bench.mkdir(exist_ok=True)

    with open(bench / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    lines = ["| Signals (N) | Engine | Violations | Cabinets / LB | Gap | Rev B moves (ours / scratch) | Runtime (s) |",
             "|---|---|---|---|---|---|---|"]
    table, chart = [], []
    for r in results:
        n, lb = r["N"], r["LB"]
        pct = lambda m, u: f"{100.0*m/max(1,u):.1f}%" if u else "-"
        lines.append(f"| {n:,} | B0 Greedy (File Order) | {r['B0_violations']} | "
                     f"{r['B0_cabinets']} / {lb} | {r['B0_cabinets']-lb} | - | {r['B0_wall_s']} |")
        lines.append(f"| {n:,} | B1 Greedy (Grouped + A/B) | {r['B1_violations']} | "
                     f"{r['B1_cabinets']} / {lb} | {r['B1_cabinets']-lb} | - | {r['B1_wall_s']} |")
        lines.append(f"| {n:,} | **CHARMSAT (3-stage)** | **{r['revA_violations']}** | "
                     f"**{r['revA_cabinets']} / {lb}** | **{r['gap']}** | "
                     f"**{r['moves_ours']} ({pct(r['moves_ours'], r['unchanged'])}) / "
                     f"{r['moves_scratch']} ({pct(r['moves_scratch'], r['unchanged'])})** | "
                     f"**{r['revA_wall_s']}** |")
        for eng, cabs, viols, moves, wall in (
                ("B0 Greedy (File Order)", r["B0_cabinets"], r["B0_violations"], None, r["B0_wall_s"]),
                ("B1 Greedy (Grouped + A/B)", r["B1_cabinets"], r["B1_violations"], None, r["B1_wall_s"]),
                ("CHARMSAT (3-stage)", r["revA_cabinets"], r["revA_violations"],
                 r["moves_ours"], r["revA_wall_s"])):
            table.append({"N": n, "engine": eng, "violations": viols, "cabinets": cabs,
                          "lb": lb, "gap": cabs - lb, "rev_b_moves": moves,
                          "rev_b_scratch": r["moves_scratch"] if eng.startswith("CHARMSAT") else None,
                          "runtime_s": wall,
                          "verdict": ("FAIL (Violates Rules)" if viols else
                                      ("OPTIMAL (matches lower bound)" if cabs == lb else f"GAP {cabs-lb}"))})
        chart.append({"signals": n, "b0": r["B0_wall_s"], "b1": r["B1_wall_s"],
                      "charmsat": r["revA_wall_s"]})
    (bench / "results.md").write_text(
        f"# CHARMSAT benchmark ({meta['date'][:10]}, commit {meta['commit']})\n\n" +
        "\n".join(lines) + "\n")
    (bench / "results.json").write_text(json.dumps(
        {"meta": meta, "table": table, "chart": chart}, indent=1))
    (bench / "meta.json").write_text(json.dumps(meta, indent=1))
    print("\n".join(lines))
    print(f"\nwrote bench/results.csv, results.md, results.json, meta.json "
          f"[{meta['machine']}, {meta['cpu_count']} CPUs, {meta['date'][:10]}]")


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [1000, 5000, 10000])
