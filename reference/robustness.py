"""Robustness runs: random rule variants + adversarial defects + a live-added rule. All results measured."""
import copy, random, time, json
import charmsat_core as E
import independent_checker as C


def run_case(sig, sizes, rules):
    r = E.allocate(sig, sizes, rules)
    if not r["ok"]:
        return {"ok": False, "tqs": r["tqs"][-1:]}
    tq_tags = {t for q in r["tqs"] for t in q.get("items", [])}
    waived = {q["id"][len("TQ-CAP-"):] for q in r["tqs"] if q["id"].startswith("TQ-CAP-")}
    v = C.check([s.__dict__ for s in sig], r["rows"], rules, E.HW_TABLE, {c.id: c.size for c in r["cables"]}, tq_tags, waived)
    placed = {row["tag"] for row in r["rows"] if row["tag"]}
    covered = sum(1 for s in sig if s.tag in placed or s.tag in tq_tags)
    real = [x for x in v if x["status"] == "violation"]
    return {"ok": True, "violations": len(real), "waived_by_tq": len(v) - len(real), "first": real[:2],
            "coverage": round(100 * covered / len(sig), 2),
            "cabinets": r["cabinets"], "lb": r["lower_bounds"]["best"], "tqs": len(r["tqs"])}


# 1) random rule variants
rng = random.Random(1)
results = []
t0 = time.time()
for case in range(40):
    rules = copy.deepcopy(E.DEFAULT_RULES)
    rules["segregation"][0]["level"] = rng.choice(["cioc", "cioc", "cabinet", "baseplate"])
    rules["spare"]["percent"] = rng.choice([0, 10, 12.5, 15, 20])
    rules["spare"]["rounding"] = rng.choice(["ceil", "floor", "round"])
    rules["group_cohesion"]["enabled"] = rng.random() < 0.85
    n = rng.randint(150, 1500)
    sig, sizes = E.generate(n, seed=rng.randint(1, 10**6), ungrouped_frac=rng.choice([0, 0.05, 0.3]),
                            ab_frac=rng.choice([0, 0.35, 0.8]))
    res = run_case(sig, sizes, rules)
    results.append(res)
fails = [r for r in results if not r["ok"] or r["violations"]]
print(json.dumps({"random_variants": len(results), "failures": len(fails), "examples": fails[:2],
                  "min_coverage": min(r.get("coverage", 0) for r in results),
                  "cabinets_eq_lb": sum(1 for r in results if r.get("cabinets") == r.get("lb")),
                  "wall_s": round(time.time() - t0, 1)}))

# 2) adversarial file: every defect class at once
rules = copy.deepcopy(E.DEFAULT_RULES)
sig, sizes = E.generate(1200, seed=5)
sig[3].tag = sig[2].tag                                    # duplicate tag
sig[10].pair = 40                                          # pair beyond cable size
cab = sig[20].cable
for s in sig:
    if s.cable == cab:
        s.seg = "A"
sig[[i for i, s in enumerate(sig) if s.cable == cab][-1]].seg = "B"   # A and B on one cable
sig[30].io_type = "PI"                                     # unknown signal type
for s in sig[:430]:
    s.group = "GIANT"                                      # group larger than any cabinet
print(json.dumps({"adversarial": run_case(sig, sizes, rules)}))

# 3) live-added rule: AC and DC never share a baseplate (Emerson recommends separating AC from low-voltage signals)
sig, sizes = E.generate(1500, seed=11, ac_frac=0.1)
base = copy.deepcopy(E.DEFAULT_RULES)
plus = copy.deepcopy(E.DEFAULT_RULES)
plus["segregation"].append({"id": "R7-ACDC", "attribute": "voltage", "classes": ["AC", "DC"], "level": "baseplate", "enabled": True})
a, b = run_case(sig, sizes, base), run_case(sig, sizes, plus)
# what the checker says about the base allocation under the NEW rule (proves the rule bites)
ra = E.allocate(sig, sizes, base)
v_new = C.check([s.__dict__ for s in sig], ra["rows"], plus, E.HW_TABLE, {c.id: c.size for c in ra["cables"]})
print(json.dumps({"new_rule": {"without_rule": a, "with_rule": b,
                               "old_allocation_checked_against_new_rule_violations": len(v_new)}}))
