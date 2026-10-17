"""
Independent checker. Imports nothing from the engine or the app.

Inputs are only what a reviewer would hold: the customer IO list rows, the
allocation rows (as read back from the exported workbook), the rule set and
the hardware table, all as plain dicts.
Every rule is re-derived from those rows.

Workbook helpers (read_workbook_rows, plant_violation) use openpyxl only to
parse the FILE - never engine state. Attributes always come from the IO list.
"""
import copy
import io as _io
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
    _LEVEL_KEY = {"cabinet": lambda r: (r["cabinet"],),
                  "cioc": lambda r: (r["cabinet"], r["cioc"]),
                  "baseplate": lambda r: (r["cabinet"], r["cioc"], r["baseplate"])}
    for rule in rules["segregation"]:
        if not rule["enabled"]:
            continue
        key = _LEVEL_KEY[rule["level"]]
        classes = defaultdict(set)
        rule_classes = rule.get("classes")  # None/[] = ALL_DISTINCT
        for r in alloc_rows:
            val = attr(r, rule["attribute"])
            if not val:
                continue
            if rule_classes is None or not rule_classes or val in rule_classes:
                classes[key(r)].add(val)
        for unit, vals in classes.items():
            if len(vals) > 1:
                bad(rule["id"], f"{rule['level']} {unit} mixes {sorted(vals)}")

    # 3b. cohesion rules: same attribute value stays in the same unit
    for rule in rules.get("cohesion", []):
        if not rule.get("enabled", True):
            continue
        key = _LEVEL_KEY[rule["level"]]
        units_of = defaultdict(set)
        for r in alloc_rows:
            val = attr(r, rule["attribute"])
            if val:
                units_of[val].add(key(r))
        for val, units in units_of.items():
            if len(units) > 1:
                bad(rule["id"], f"{rule['attribute']} '{val}' is split across "
                                f"{rule['level']}s {sorted(units)} (rule {rule['id']})")

    # 3c. capacity rules (at_most_k): <= k distinct attribute values per unit
    for rule in rules.get("capacity", []):
        if not rule.get("enabled", True):
            continue
        key = _LEVEL_KEY[rule["level"]]
        values_of = defaultdict(set)
        for r in alloc_rows:
            val = attr(r, rule["attribute"])
            if val:
                values_of[key(r)].add(val)
        for unit, vals in values_of.items():
            if len(vals) > rule["k"]:
                bad(rule["id"], f"{rule['level']} {unit} has {len(vals)} distinct "
                                f"{rule['attribute']} values {sorted(vals)}; rule {rule['id']} "
                                f"allows at most {rule['k']}")

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


# --------------------------------------------------------------------------------------
# Workbook I/O (file parsing only - no engine state; openpyxl is a library, not the app)
# --------------------------------------------------------------------------------------
def _col_letter(col):
    if isinstance(col, int):
        s = ""
        while col > 0:
            col, rem = divmod(col - 1, 26)
            s = chr(65 + rem) + s
        return s
    return str(col).strip().upper()


def read_workbook_rows(workbook_bytes, template_map):
    """Allocation rows as plain dicts, read back from the WRITTEN workbook."""
    import openpyxl
    wb = openpyxl.load_workbook(_io.BytesIO(workbook_bytes), data_only=True)
    sheet = template_map.get("allocation_sheet")
    if sheet not in wb.sheetnames:
        raise ValueError(f"sheet '{sheet}' not in workbook")
    ws = wb[sheet]
    first = int(template_map.get("first_data_row", 2))
    columns = template_map.get("columns", {})
    rows = []
    for r in range(first, ws.max_row + 1):
        tag = ws[f"{_col_letter(columns.get('tag', 'A'))}{r}"].value
        cable = ws[f"{_col_letter(columns.get('cable', 'B'))}{r}"].value
        if tag is None and cable is None:
            continue  # trailing blank row, not a signal
        vals = {}
        for field, col in columns.items():
            v = ws[f"{_col_letter(col)}{r}"].value
            vals[field] = "" if v is None else v
        rows.append({
            "tag": str(vals.get("tag", "") or ""),
            "cable": str(vals.get("cable", "") or ""),
            "pair": int(vals.get("pair", 0) or 0),
            "cabinet": int(vals.get("cabinet", 0) or 0),
            "cioc": int(vals.get("cioc", 0) or 0),
            "baseplate": int(vals.get("baseplate", 0) or 0),
            "slot": int(vals.get("slot", 0) or 0),
            "charm": str(vals.get("charm", "") or ""),
            "tb": str(vals.get("tb", "") or ""),
        })
    return rows


def plant_violation(workbook_bytes, template_map, plant_type="ab_leak"):
    """Deliberately corrupt a COPY of a correct workbook (credibility demo).

    Returns the tampered workbook bytes. Every plant type is caught 100% by
    check() - enforced by test_planted.py.
    """
    import openpyxl
    wb = openpyxl.load_workbook(_io.BytesIO(workbook_bytes))
    ws = wb[template_map.get("allocation_sheet")]
    first = int(template_map.get("first_data_row", 2))
    columns = template_map.get("columns", {})

    def col(field):
        return _col_letter(columns.get(field, "A"))

    def nrows():
        return ws.max_row - first + 1

    def get(r, field):
        return ws[f"{col(field)}{first + r}"].value

    def put(r, field, value):
        ws[f"{col(field)}{first + r}"].value = value

    n = nrows()
    if plant_type == "ab_leak":
        # NOTE: the checker reads seg from the IO list and the unit from the
        # workbook, so the plant must move a row's ALLOCATION into a CIOC of
        # the other train (editing the seg cell alone proves nothing).
        units = defaultdict(set)
        for i in range(n):
            if get(i, "tag"):
                units[(get(i, "cabinet"), get(i, "cioc"))].add(str(get(i, "seg") or ""))
        # Pure = one train only (neutral "" signals may share the CIOC).
        pure_a = next((k for k, v in units.items() if "A" in v and "B" not in v), None)
        pure_b = next((k for k, v in units.items() if "B" in v and "A" not in v), None)
        if pure_a is not None:
            i = next(i for i in range(n) if str(get(i, "seg") or "") == "B")
            put(i, "cabinet", pure_a[0])
            put(i, "cioc", pure_a[1])
        elif pure_b is not None:
            i = next(i for i in range(n) if str(get(i, "seg") or "") == "A")
            put(i, "cabinet", pure_b[0])
            put(i, "cioc", pure_b[1])
        else:
            raise ValueError("no segregated CIOCs to leak between")
    elif plant_type == "split_cable":
        # Shift one pair of a multi-pair cable 5 slots away.
        cables = defaultdict(list)
        for i in range(n):
            cables[str(get(i, "cable"))].append(i)
        cid = next(c for c, members in cables.items() if len(members) > 2)
        i = cables[cid][1]
        put(i, "slot", ((int(get(i, "slot") or 1) + 5 - 1) % 12) + 1)
    elif plant_type == "wrong_tb":
        i = next(i for i in range(n) if get(i, "tag"))
        put(i, "tb", "Wrong TB")
    elif plant_type == "straddle":
        # Shift a 24-pair cable's start by one slot: still contiguous and
        # valid, but no longer on a baseplate boundary (pure CABLE catch).
        cables = defaultdict(list)
        for i in range(n):
            cables[str(get(i, "cable"))].append(i)
        big = [c for c, m in cables.items() if len(m) == 24]
        if big:
            members = sorted(cables[big[0]],
                             key=lambda i: (int(get(i, "baseplate") or 1), int(get(i, "slot") or 1)))
            lin0 = (int(get(members[0], "baseplate") or 1) - 1) * 12 + \
                (int(get(members[0], "slot") or 1) - 1)
            for k, i in enumerate(members):
                lin = lin0 + 1 + k
                put(i, "baseplate", lin // 12 + 1)
                put(i, "slot", lin % 12 + 1)
        else:  # fallback: nudge one pair off contiguity
            cid = max(cables, key=lambda c: len(cables[c]))
            i = cables[cid][1]
            put(i, "slot", ((int(get(i, "slot") or 1) + 3 - 1) % 12) + 1)
    elif plant_type == "spare_breach":
        # Genuinely breach R5-SPARE: repack every row into cabinet 1 on
        # distinct slots until 0 baseplates are empty (need >= 4 at 10%).
        # Layout: (cioc, bp) cycles 32 combos, slot cycles 1..12 without
        # collision. Other rules (CABLE, A/B) may fire too; R5-SPARE must.
        for i in range(n):
            put(i, "cabinet", 1)
            put(i, "cioc", (i // 8) % 4 + 1)
            put(i, "baseplate", (i % 8) + 1)
            put(i, "slot", (i // 32) % 12 + 1)
    elif plant_type == "missing_signal":
        tagged = [i for i in range(n) if get(i, "tag")]
        if not tagged:
            raise ValueError("no tagged rows to delete")
        ws.delete_rows(first + tagged[-1])
    elif plant_type == "duplicate":
        # Copy row 0's tag onto row 1 (same tag placed twice).
        put(1, "tag", get(0, "tag"))
    else:
        raise ValueError(f"unknown plant_type {plant_type!r}")
    buf = _io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
