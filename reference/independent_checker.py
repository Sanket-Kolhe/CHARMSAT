"""
Independent checker. Imports nothing from the engine.

Inputs are only what a reviewer would hold: the customer IO list rows, the allocation rows (as read back
from the exported workbook), the rule set and the hardware table, all as plain dicts.
Every rule is re-derived from those rows.
"""
import math
from collections import defaultdict


def check(io_rows, alloc_rows, rules, hw_table, cable_sizes, tq_tags=frozenset(), waived_groups=frozenset()):
    v = []

    def bad(rule, msg, tag=None):
        # a breach that an open TQ already explains is reported as waived, never hidden and never "clean"
        v.append({"rule": rule, "message": msg, "status": "waived_by_tq" if tag in tq_tags else "violation"})

    hw = rules["hardware"]
    n_cioc, n_bp, n_slot = hw["cabinet_ciocs"], hw["cioc_baseplates"], hw["baseplate_slots"]

    # 0. coverage: every input signal placed exactly once, or held by a TQ
    placed = defaultdict(int)
    for r in alloc_rows:
        if r["tag"]:
            placed[r["tag"]] += 1
    for s in io_rows:
        n = placed.get(s["tag"], 0)
        if n == 0 and s["tag"] not in tq_tags:
            bad("COVERAGE", f"{s['tag']} is neither placed nor covered by a TQ")
        if n > 1:
            bad("COVERAGE", f"{s['tag']} placed {n} times")
    known = {s["tag"] for s in io_rows}
    for t in placed:
        if t not in known:
            bad("COVERAGE", f"{t} placed but not in the IO list")

    # 1. addressing and slot exclusivity
    occ = defaultdict(list)
    for r in alloc_rows:
        if not (1 <= r["cioc"] <= n_cioc and 1 <= r["baseplate"] <= n_bp and 1 <= r["slot"] <= n_slot):
            bad("CAPACITY", f"{r['cable']}/{r['pair']} at invalid address {r['cioc']}/{r['baseplate']}/{r['slot']}")
        occ[(r["cabinet"], r["cioc"], r["baseplate"], r["slot"])].append(r)
    for k, rs in occ.items():
        if len(rs) > 1:
            bad("CAPACITY", f"position {k} used by {[(x['cable'], x['pair']) for x in rs]}")

    # 2. cable kept together, in pair order, aligned
    by_cable = defaultdict(list)
    for r in alloc_rows:
        by_cable[r["cable"]].append(r)
    io_by_cable = defaultdict(dict)
    for s in io_rows:
        io_by_cable[s["cable"]][s["pair"]] = s
    for cid, rs in by_cable.items():
        rs = sorted(rs, key=lambda r: r["pair"])
        size = cable_sizes[cid]
        if [r["pair"] for r in rs] != list(range(1, size + 1)):
            bad("CABLE", f"{cid}: pairs present {[r['pair'] for r in rs]} but cable has {size}")
            continue
        if len({(r["cabinet"], r["cioc"]) for r in rs}) > 1:
            bad("CABLE", f"{cid} split across CIOCs")
            continue
        lin = [(r["baseplate"] - 1) * n_slot + (r["slot"] - 1) for r in rs]
        if lin != list(range(lin[0], lin[0] + size)):
            bad("CABLE", f"{cid} not contiguous in pair order")
        if size >= n_slot and lin[0] % n_slot != 0:
            bad("CABLE", f"{cid} ({size}-pair) does not start on a baseplate boundary")
        if size < n_slot and not rules["cable"]["small_may_straddle"] and lin[0] // n_slot != lin[-1] // n_slot:
            bad("CABLE", f"{cid} ({size}-pair) straddles two baseplates")
        for r in rs:  # tag on the right pair
            s = io_by_cable[cid].get(r["pair"])
            expected = s["tag"] if s else ""
            if expected != r["tag"] and r["tag"] not in tq_tags and expected not in tq_tags:
                bad("CABLE", f"{cid} pair {r['pair']}: expected {s['tag'] if s else 'spare'}, got {r['tag'] or 'spare'}")

    io_tag = {s["tag"]: s for s in io_rows}

    def attr(r, name):  # attributes always come from the customer IO list, never from the engine's rows
        return io_tag[r["tag"]].get(name, "") if r["tag"] in io_tag else ""

    # 3. never-share rules
    for rule in rules["segregation"]:
        if not rule["enabled"]:
            continue
        key = {"cabinet": lambda r: (r["cabinet"],), "cioc": lambda r: (r["cabinet"], r["cioc"]),
               "baseplate": lambda r: (r["cabinet"], r["cioc"], r["baseplate"])}[rule["level"]]
        classes = defaultdict(set)
        for r in alloc_rows:
            val = attr(r, rule["attribute"])
            if val in rule["classes"]:
                classes[key(r)].add(val)
        for unit, vals in classes.items():
            if len(vals) > 1:
                bad(rule["id"], f"{rule['level']} {unit} mixes {sorted(vals)}")

    # 4. group cohesion
    if rules["group_cohesion"]["enabled"]:
        cabs = defaultdict(set)
        for r in alloc_rows:
            g = attr(r, "group")
            if g and r["tag"] not in tq_tags:
                cabs[g].add(r["cabinet"])
        for g, cs in cabs.items():
            if len(cs) > 1 and g not in waived_groups:
                bad("R1-GROUP", f"group {g} spread over cabinets {sorted(cs)}")

    # 5. spare: empty baseplates per used cabinet
    pct = rules["spare"]["percent"] / 100.0
    raw = n_cioc * n_bp * pct
    need = {"ceil": math.ceil(raw - 1e-9), "floor": math.floor(raw + 1e-9), "round": int(round(raw))}[rules["spare"]["rounding"]]
    used_bp = defaultdict(set)
    for r in alloc_rows:
        used_bp[r["cabinet"]].add((r["cioc"], r["baseplate"]))
    for cab, bps in used_bp.items():
        empty = n_cioc * n_bp - len(bps)
        if empty < need:
            bad("R5-SPARE", f"cabinet {cab} has {empty} empty baseplates, needs {need}")

    # 6. hardware per signal type (table is data)
    io = {s["tag"]: s for s in io_rows}
    for r in alloc_rows:
        if not r["tag"]:
            continue
        s = io[r["tag"]]
        exp = next(((h["charm"], h["tb"]) for h in hw_table
                    if h["io_type"] == s["io_type"] and h["subtype"] in ("*", s["subtype"])), None)
        if exp is None:
            bad("R6-HW", f"{r['tag']}: no hardware rule for {s['io_type']}/{s['subtype']}", r["tag"])
        elif (r["charm"], r["tb"]) != exp:
            bad("R6-HW", f"{r['tag']}: got {r['charm']}/{r['tb']}, expected {exp[0]}/{exp[1]}", r["tag"])
    return v
