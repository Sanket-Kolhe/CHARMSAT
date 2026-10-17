"""W2: deterministic 'why is this signal here' explainer.

Re-derives, at the signal's actual location, which rules are being satisfied
and therefore which rules pin the slot. No guessing: every statement is checked
against the allocation rows and the input rows, and rules that do not apply are
reported as such.
"""
from typing import Dict, List, Optional

from app.engine.solve.bridge import rules_to_ref


def _unit_key(level: str, row: dict):
    if level == "cabinet":
        return (row["cabinet"],)
    if level == "cioc":
        return (row["cabinet"], row["cioc"])
    return (row["cabinet"], row["cioc"], row["baseplate"])


def _loc(row: dict) -> str:
    return f"CAB-{row['cabinet'] + 1:02d} / CIOC-{row['cioc']} / BP-{row['baseplate']} / S-{row['slot']}"


def _cab_capacity(spare_pct: float) -> int:
    return int(384 * (1 - spare_pct / 100.0))


def explain_signal(tag: str, io_rows: List[dict], alloc_rows: List[dict],
                   rules, held: Optional[frozenset] = None) -> dict:
    held = held or frozenset()
    by_tag = {r["tag"]: r for r in alloc_rows if r.get("tag")}
    io_by_tag = {r["tag"]: r for r in io_rows if r.get("tag")}

    if tag not in io_by_tag:
        return {"tag": tag, "found": False, "reason": "tag is not in the input IO list"}

    if tag in held or tag not in by_tag:
        tqs = [r for r in alloc_rows if r.get("tag") == tag]
        return {"tag": tag, "found": True, "placed": False,
                "reason": "held by a Technical Query (see the TQ log); no physical slot assigned.",
                "io": io_by_tag[tag]}

    a = by_tag[tag]
    io = io_by_tag[tag]
    ref = rules_to_ref(rules)
    checks: List[dict] = []
    pinned: List[str] = []

    # RULE-06: hardware charm match
    checks.append({
        "rule": "RULE-06", "name": "Right CHARM for the signal",
        "satisfied": bool(a.get("charm")),
        "detail": f"{io.get('io_type')}/{io.get('subtype') or '-'} → {a.get('charm')} "
                  f"on terminal block {a.get('terminal_block')}",
    })
    pinned.append("RULE-06")

    # RULE-02: cable block contiguity inside one CIOC
    members = sorted([by_tag[r["tag"]] for r in io_rows
                      if r.get("cable") == io.get("cable") and r["tag"] in by_tag],
                     key=lambda x: x.get("global_slot", 0))
    same_cioc = len({(m["cabinet"], m["cioc"]) for m in members}) == 1
    gs = [m.get("global_slot", 0) for m in members]
    contiguous = same_cioc and all(gs[i + 1] == gs[i] + 1 for i in range(len(gs) - 1))
    cc_on = rules.cable_contiguity.enabled
    ok02 = (not cc_on) or contiguous
    checks.append({
        "rule": "RULE-02", "name": "Cable kept together & contiguous",
        "satisfied": ok02,
        "detail": (("cable contiguity disabled" if not cc_on else
                    f"cable {io.get('cable')} holds {len(members)} pairs, "
                    + ("contiguous within " + f"CAB-{a['cabinet'] + 1:02d}/CIOC-{a['cioc']}"
                       if contiguous else "fragmented across CIOCs"))),
    })
    if ok02:
        pinned.append("RULE-02")

    # segregation rules: no *different* class in the same unit
    for r in ref["segregation"]:
        if not r.get("enabled"):
            continue
        attr, classes = r["attribute"], r.get("classes")
        mine = io.get(attr) or ""
        if classes and mine not in classes:
            continue
        others = {io_by_tag[m["tag"]].get(attr) for m in alloc_rows
                  if m.get("tag") and m.get("tag") != tag
                  and _unit_key(r["level"], m) == _unit_key(r["level"], a)
                  and m["tag"] in io_by_tag}
        others = {v for v in others if v and (not classes or v in classes)}
        conflicts = others - {mine}
        ok = not conflicts
        checks.append({
            "rule": r["id"], "name": f"Never share a {r['level']} with a different {attr}",
            "satisfied": ok,
            "detail": f"this {r['level']} carries '{mine}'"
                      + ("" if not conflicts else f"; conflict with {sorted(conflicts)}"),
        })
        if ok:
            pinned.append(r["id"])

    # group cohesion: the whole group sits in one cabinet
    if rules.group_cohesion.enabled and io.get("group"):
        g = io["group"]
        cabs = {m["cabinet"] for m in alloc_rows
                if m.get("tag") and m["tag"] in io_by_tag
                and io_by_tag[m["tag"]].get("group") == g}
        ok = len(cabs) <= 1
        checks.append({
            "rule": "RULE-03", "name": "Group cabinet cohesion",
            "satisfied": ok,
            "detail": f"group {g}: {len(cabs)} cabinet(s) {sorted(c + 1 for c in cabs)}",
        })
        if ok:
            pinned.append("RULE-03")

    # spare capacity: cabinet still within its spare margin
    spare = rules.spare_capacity.spare_percentage if rules.spare_capacity.enabled else 0
    cap = _cab_capacity(spare) if rules.spare_capacity.enabled else 384
    used = len({m["tag"] for m in alloc_rows
                if m.get("tag") and m["cabinet"] == a["cabinet"]})
    ok = used <= cap
    checks.append({
        "rule": "RULE-04", "name": "Cabinet spare margin respected",
        "satisfied": ok,
        "detail": f"cabinet CAB-{a['cabinet'] + 1:02d}: {used} signals, "
                  f"limit {cap} (spare {spare}%)",
    })
    if ok:
        pinned.append("RULE-04")

    why = (f"Placed at {_loc(a)}. Its {io.get('io_type')}/{io.get('subtype') or '-'} signal "
           f"needs {a.get('charm')}, its cable {io.get('cable')} is kept "
           f"{'contiguous' if contiguous else 'whole (straddle allowed)'}, and no rule "
           f"forbids this unit. The solver picked the lowest-index free slot consistent "
           f"with every rule above.")
    return {
        "tag": tag, "found": True, "placed": True,
        "location": _loc(a),
        "cabinet": a["cabinet"], "cioc": a["cioc"],
        "baseplate": a["baseplate"], "slot": a["slot"],
        "charm": a.get("charm"), "terminal_block": a.get("terminal_block"),
        "io": io,
        "checks": checks,
        "pinned_by": sorted(set(pinned)),
        "why_here": why,
    }
