"""
One-command benchmark for the prototype. Every number printed is measured in this run.
Usage: python bench.py 1000 5000 10000
"""
import copy
import hashlib
import json
import sys
import time
from collections import defaultdict

import charmsat_core as E
import independent_checker as C


def io_rows(sig):
    return [s.__dict__ for s in sig]


def tq_tags(res):
    return {t for q in res["tqs"] for t in q.get("items", [])}


def waived(res):
    return {q["id"][len("TQ-CAP-"):] for q in res["tqs"] if q["id"].startswith("TQ-CAP-")}


def b1_greedy(sig, sizes, rules):
    """Honest grouped greedy baseline: same rules, no optimisation. Unit order = order of first appearance."""
    t0 = time.time()
    cables, tqs = E.build_cables(sig, sizes, rules)
    units = E.make_units(cables, rules, tqs)
    first_seen = {}
    for i, s in enumerate(sig):
        first_seen.setdefault(s.group or f"__free__{s.cable}", i)
    units.sort(key=lambda u: first_seen.get(u.id.split("#")[0], 0))
    cabs = []          # list of lists of units
    for u in units:
        placed = False
        for members in cabs:
            if E.cabinet_relaxation_ok(members + [u], rules) and _greedy_cab_ok(members + [u], rules):
                members.append(u)
                placed = True
                break
        if not placed:
            cabs.append([u])
    return {"cabinets": len(cabs), "runtime_s": round(time.time() - t0, 2)}


def _greedy_cab_ok(units, rules):
    """First-fit cables (in unit order) into 4 CIOCs respecting A/B and capacity."""
    usable = E.BP_PER_CAB - E.spare_baseplates(rules)
    fill, cls = [0] * 4, [""] * 4
    rid = rules["segregation"][0]["id"]
    for u in units:
        for c in u.cables:
            col = c.color.get(rid, "")
            for k in range(4):
                if fill[k] + c.size <= 96 and (not col or not cls[k] or cls[k] == col):
                    fill[k] += c.size
                    cls[k] = cls[k] or col
                    break
            else:
                return False
    return sum(-(-f // 12) for f in fill) <= usable


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:12]


def run(n):
    rules = copy.deepcopy(E.DEFAULT_RULES)
    sig_a, sizes_a = E.generate(n, seed=42)
    t = time.time()
    ra = E.allocate(sig_a, sizes_a, rules)
    wall_a = time.time() - t
    viol_a = C.check(io_rows(sig_a), ra["rows"], rules, E.HW_TABLE, {c.id: c.size for c in ra["cables"]},
                     tq_tags(ra), waived(ra))
    ra2 = E.allocate(sig_a, sizes_a, rules)
    deterministic = digest(ra["rows"]) == digest(ra2["rows"])
    b1 = b1_greedy(sig_a, sizes_a, rules)

    sig_b, sizes_b, meta = E.generate_revision(sig_a, sizes_a)
    prev = {cid: p for cid, p in ra["placements"].items()}
    t = time.time()
    rb = E.allocate(sig_b, sizes_b, rules, prev=prev)
    wall_b = time.time() - t
    if not rb["ok"]:
        print(json.dumps({"N": n, "revB_failed": rb["tqs"][-3:]}), flush=True)
        return None
    viol_b = C.check(io_rows(sig_b), rb["rows"], rules, E.HW_TABLE, {c.id: c.size for c in rb["cables"]},
                     tq_tags(rb), waived(rb))
    mv = E.count_moves(ra["rows"], rb["rows"], sig_a, sig_b)
    rs = E.allocate(sig_b, sizes_b, rules)                     # from scratch on Rev B
    ms = E.count_moves(ra["rows"], rs["rows"], sig_a, sig_b)
    out = {
        "N": n, "cables": len(ra["cables"]),
        "revA_cabinets": ra["cabinets"], "LB_slots": ra["lower_bounds"]["slots"],
        "LB_segregation": ra["lower_bounds"]["segregated_ciocs"], "stage1_status": ra["stage1"]["status"],
        "stage1_bound": ra["stage1"]["bound"], "benders_cuts": ra["benders_cuts"],
        "revA_wall_s": round(wall_a, 2), "revA_violations": sum(1 for x in viol_a if x["status"] == "violation"), "deterministic": deterministic,
        "B1_cabinets": b1["cabinets"], "revB_meta": meta, "revB_cabinets": rb["cabinets"],
        "revB_wall_s": round(wall_b, 2), "revB_violations": sum(1 for x in viol_b if x["status"] == "violation"),
        "moves_ours": mv["moved"], "moves_ours_cabinet_change": mv["moved_cabinet"],
        "moves_scratch": ms["moved"], "scratch_cabinets": rs["cabinets"],
        "unchanged_inputs": mv["unchanged_inputs"], "tqs_A": len(ra["tqs"]),
        "sample_violation": (viol_a + viol_b)[:2],
    }
    print(json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    for n in [int(a) for a in sys.argv[1:]] or [1000]:
        run(n)
