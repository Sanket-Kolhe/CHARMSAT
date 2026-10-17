"""
CHARMSAT core prototype (reference implementation for the build playbook).

Three-stage decomposition for DeltaV CHARM allocation:
  Stage 1  units (groups / free cables) -> cabinet      CP-SAT, aggregated rules, gives a proven lower bound
  Stage 2  cables -> CIOC inside one cabinet            CP-SAT, exact per cabinet, small
  Stage 3  cables -> baseplate/slot inside one CIOC     constructive first-fit-decreasing (exact for
                                                        divisible cable sizes 2|6|12|24), CP-SAT fallback
Infeasible stage-2 cabinets feed a no-good cut back to stage 1 (logic-based Benders loop).

Revision (Rev A -> Rev B) uses the same stages with "keep" literals weighted by the number of
signals a move would disturb, so unchanged signals stay put unless a rule forces a move.

The independent checker lives in independent_checker.py and imports nothing from this file.
"""
from __future__ import annotations

import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

SLOTS_PER_BP = 12
BP_PER_CIOC = 8
CIOC_PER_CAB = 4
SLOTS_PER_CIOC = SLOTS_PER_BP * BP_PER_CIOC          # 96
BP_PER_CAB = BP_PER_CIOC * CIOC_PER_CAB              # 32


# ----------------------------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------------------------
@dataclass
class Signal:
    tag: str
    io_type: str
    subtype: str
    cable: str
    pair: int
    group: str
    seg: str            # "A", "B" or ""
    voltage: str = "DC"  # used by the live-added rule demo (AC vs DC)


@dataclass
class Cable:
    id: str
    size: int
    signals: List[Signal] = field(default_factory=list)
    group: str = ""
    color: Dict[str, str] = field(default_factory=dict)   # rule_id -> class value ("" = neutral)
    cohesion: Dict[str, str] = field(default_factory=dict)  # cohesion rule_id -> shared value

    @property
    def used(self) -> int:
        return len(self.signals)


@dataclass
class Placement:
    cabinet: int
    cioc: int
    start: int      # slot index inside the CIOC, 0..95


DEFAULT_RULES = {
    "hardware": {"cabinet_ciocs": 4, "cioc_baseplates": 8, "baseplate_slots": 12},
    "hardware_table": None,
    "spare": {"percent": 10.0, "unit": "baseplate", "rounding": "ceil"},
    "group_cohesion": {"enabled": True, "level": "cabinet", "on_oversize": "split_with_tq"},
    "segregation": [
        # generic never_share rules: cables of different classes never share the unit at `level`
        {"id": "R2-AB", "attribute": "seg", "classes": ["A", "B"], "level": "cioc", "enabled": True},
    ],
    "cohesion": [],   # generic "same" rules: {id, attribute, level}
    "capacity": [],   # generic "at_most_k" rules: {id, attribute, level, k}
    "cable": {"small_may_straddle": False, "spare_pairs_occupy_slots": True},
    "solver": {"det_time_stage1": 3.0, "det_time_balance": 2.0, "det_time_stage2": 1.0, "workers": 8, "seed": 7,
               "max_benders_iters": 8, "cabinet_cost_in_moves": 200, "design_for_change": True},
}


# Synthetic data lives in app/engine/generator.py (unique tags, free-pair Rev B).
# This port keeps only the solver stages from reference/charmsat_core.py.


# ----------------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------------
def spare_baseplates(rules) -> int:
    """Empty baseplates each used cabinet must keep. 10% of 32 = 3.2 -> 4 with 'ceil' (never below 10%)."""
    raw = BP_PER_CAB * rules["spare"]["percent"] / 100.0
    mode = rules["spare"]["rounding"]
    if mode == "ceil":
        return math.ceil(raw - 1e-9)
    if mode == "floor":
        return math.floor(raw + 1e-9)
    return int(round(raw))


def build_cables(signals: List[Signal], sizes: Dict[str, int], rules) -> Tuple[List[Cable], List[dict]]:
    """Cable blocks + data TQs. Every signal ends up either in a cable block or in a TQ."""
    hw_table = rules.get("hardware_table")
    tqs, by_cable = [], defaultdict(list)
    seen_tag = {}
    for s in signals:
        if s.tag in seen_tag:
            tqs.append({"id": f"TQ-DUP-{s.tag}", "kind": "data", "items": [s.tag, seen_tag[s.tag].tag],
                        "message": f"Tag {s.tag} appears twice (cables {seen_tag[s.tag].cable}/{s.cable}); both held."})
            continue
        seen_tag[s.tag] = s
        by_cable[s.cable].append(s)
    held = {t for q in tqs for t in q["items"]}
    cables = []
    for cid in sorted(by_cable):
        sigs = sorted((s for s in by_cable[cid] if s.tag not in held), key=lambda s: s.pair)
        if not sigs:
            continue
        size = sizes.get(cid) or next((k for k in (2, 6, 12, 24, 48) if k >= max(s.pair for s in sigs)), 0)
        bad_pairs = [s for s in sigs if s.pair < 1 or s.pair > size]
        dup_pairs = [s for i, s in enumerate(sigs) if i and s.pair == sigs[i - 1].pair]
        if bad_pairs or dup_pairs or size == 0:
            tqs.append({"id": f"TQ-PAIR-{cid}", "kind": "data", "items": [s.tag for s in sigs],
                        "message": f"Cable {cid} (size {size}) has pair numbers out of range or used twice: "
                                   f"{sorted({s.pair for s in bad_pairs + dup_pairs})}. Cable held until corrected."})
            continue
        c = Cable(cid, size, sigs, group=sigs[0].group)
        for sg in sigs:
            if _hw(sg, hw_table) == (None, None):
                tqs.append({"id": f"TQ-HW-{sg.tag}", "kind": "data", "items": [sg.tag],
                            "message": f"No CHARM/terminal-block rule matches {sg.tag} ({sg.io_type}/{sg.subtype or '-'}). "
                                       f"Position reserved on {cid} pair {sg.pair}; add a hardware rule or correct the type."})
        groups = {s.group for s in sigs}
        if len(groups) > 1:
            minority = [s.tag for s in sigs if s.group != c.group]
            tqs.append({"id": f"TQ-GRP-{cid}", "kind": "data", "items": minority,
                        "message": f"Cable {cid} carries signals of several groups {sorted(groups)}. The cable cannot be "
                                   f"split, so it follows group {c.group}; {len(minority)} signal(s) of the other group(s) "
                                   f"may sit in a different cabinet from their group. Please confirm."})
        bad = False
        # never-share (segregation): classes may be enumerated, or None = ALL_DISTINCT
        for r in rules["segregation"]:
            if not r["enabled"]:
                continue
            raw = {getattr(s, r["attribute"]) for s in sigs if getattr(s, r["attribute"])}
            vals = raw & set(r["classes"]) if r.get("classes") else raw
            if len(vals) > 1:
                tqs.append({"id": f"TQ-CONFLICT-{cid}", "kind": "rule_conflict", "items": [s.tag for s in sigs],
                            "rules": [r["id"], "R4-CABLE-BLOCK"], "mus": [r["id"], "R4-CABLE-BLOCK"],
                            "message": f"Cable {cid} mixes {sorted(vals)} on '{r['attribute']}': rule {r['id']} "
                                       f"(never share a {r['level']}) and the keep-cable-together rule cannot both hold. "
                                       f"Minimal conflict: {r['id']} needs these values apart; R4-CABLE-BLOCK keeps this "
                                       f"cable atomic. Fix: split the cable or correct the {r['attribute']} column."})
                bad = True
            c.color[r["id"]] = next(iter(vals)) if len(vals) == 1 else ""
        # cohesion (same): a cable must carry one value of the attribute; mixed -> cannot split
        for r in rules.get("cohesion", []):
            if not r.get("enabled", True):
                continue
            raw = {getattr(s, r["attribute"]) for s in sigs if getattr(s, r["attribute"])}
            c.cohesion[r["id"]] = next(iter(raw)) if len(raw) == 1 else ""
            if len(raw) > 1:
                tqs.append({"id": f"TQ-COH-{cid}", "kind": "rule_conflict", "items": [s.tag for s in sigs],
                            "rules": [r["id"], "R4-CABLE-BLOCK"], "mus": [r["id"], "R4-CABLE-BLOCK"],
                            "message": f"Cable {cid} mixes {sorted(raw)} on '{r['attribute']}': rule {r['id']} "
                                       f"(same {r['level']}) and the keep-cable-together rule cannot both hold. "
                                       f"Fix: split the cable or correct the {r['attribute']} column."})
                bad = True
        if not bad:
            cables.append(c)
    return cables, tqs

def bp_need(slots: int) -> int:
    return -(-slots // SLOTS_PER_BP)


# ----------------------------------------------------------------------------------------------
# Lower bounds (all valid for the rule set; reported side by side)
# ----------------------------------------------------------------------------------------------
def lower_bounds(cables: List[Cable], rules) -> Dict[str, int]:
    usable_bp = BP_PER_CAB - spare_baseplates(rules)
    total = sum(c.size for c in cables)
    lb_slots = -(-total // (usable_bp * SLOTS_PER_BP))
    cioc_rules = [r for r in rules["segregation"] if r["enabled"] and r["level"] == "cioc"]
    lb_cioc = 0
    if cioc_rules:
        r = cioc_rules[0]
        per_class = defaultdict(int)
        for c in cables:
            per_class[c.color.get(r["id"], "")] += c.size
        ciocs = sum(-(-v // SLOTS_PER_CIOC) for k, v in per_class.items() if k)
        neutral_left = per_class.get("", 0) - sum((-(-v // SLOTS_PER_CIOC)) * SLOTS_PER_CIOC - v
                                                  for k, v in per_class.items() if k)
        ciocs += max(0, -(-neutral_left // SLOTS_PER_CIOC))
        lb_cioc = -(-ciocs // CIOC_PER_CAB)
    return {"slots": lb_slots, "segregated_ciocs": lb_cioc, "best": max(lb_slots, lb_cioc)}


# ----------------------------------------------------------------------------------------------
# Units for stage 1
# ----------------------------------------------------------------------------------------------
@dataclass
class Unit:
    id: str
    cables: List[Cable]
    load: Dict[Tuple[str, str], int]      # (rule_id, class) -> slots ; ("", "") = total
    values: Dict[Tuple[str, str], int] = field(default_factory=dict)  # (cap_rule_id, value) -> slots

    @property
    def total(self) -> int:
        return self.load[("", "")]


def _unit_values(units: List["Unit"], rule_id: str) -> set:
    """Distinct values of a capacity attribute present across these units."""
    return {v for u in units for (rid, v) in u.values if rid == rule_id and v}


def _cap_violation(units: List["Unit"], rules) -> bool:
    """True when the units together exceed any cabinet-level at_most_k rule."""
    for r in rules.get("capacity", []):
        if r.get("level") != "cabinet" or not r.get("enabled", True):
            continue
        if len(_unit_values(units, r["id"])) > r["k"]:
            return True
    return False


def why_not_fit(us: List["Unit"], rules) -> List[str]:
    """Plain-English reasons a set of units cannot share one empty cabinet (each names its rule)."""
    usable_bp = BP_PER_CAB - spare_baseplates(rules)
    reasons, total = [], sum(u.total for u in us)
    if bp_need(total) > usable_bp:
        reasons.append(f"needs {bp_need(total)} baseplates but a cabinet offers {usable_bp} "
                       f"after the {rules['spare']['percent']}% spare rule (R5-SPARE)")
    for r in rules["segregation"]:
        if not r["enabled"]:
            continue
        loads = {k: sum(u.load.get((r["id"], k), 0) for u in us) for k in (r.get("classes") or [])}
        present = [k for k, v in loads.items() if v]
        if r["level"] == "cabinet" and len(present) > 1:
            reasons.append(f"contains {' and '.join(present)} signals, which rule {r['id']} keeps in different cabinets")
        if r["level"] == "cioc" and sum(-(-v // SLOTS_PER_CIOC) for v in loads.values()) > CIOC_PER_CAB:
            reasons.append(f"needs more than {CIOC_PER_CAB} CIOCs once {' / '.join(present)} are separated (rule {r['id']})")
    for r in rules.get("capacity", []):
        if r.get("level") == "cabinet" and r.get("enabled", True):
            vals = _unit_values(us, r["id"])
            if len(vals) > r["k"]:
                reasons.append(f"carries {len(vals)} distinct {r['attribute']} values but rule {r['id']} allows "
                               f"at most {r['k']} per cabinet")
    return reasons or ["per-CIOC packing could not be completed"]


def make_units(cables: List[Cable], rules, tqs: List[dict]) -> List[Unit]:
    cohesion_rules = [r for r in rules.get("cohesion", []) if r.get("enabled", True)]
    capacity_rules = [r for r in rules.get("capacity", []) if r.get("enabled", True)]

    def cohesion_label(c: Cable) -> str:
        parts = []
        if rules["group_cohesion"]["enabled"] and c.group:
            parts.append(f"group={c.group}")
        for r in cohesion_rules:
            v = c.cohesion.get(r["id"], "")
            if v:
                parts.append(f"{r['id']}={v}")
        return "|".join(parts)

    by_group = defaultdict(list)
    for c in cables:
        label = cohesion_label(c)
        by_group[label or f"__free__{c.id}"].append(c)

    def unit_of(uid, cs):
        load = defaultdict(int)
        values = defaultdict(int)
        for c in cs:
            load[("", "")] += c.size
            for r in rules["segregation"]:
                if r["enabled"]:
                    load[(r["id"], c.color.get(r["id"], ""))] += c.size
            for r in capacity_rules:
                for s in c.signals:
                    if getattr(s, r["attribute"], ""):
                        values[(r["id"], getattr(s, r["attribute"]))] += 1
        return Unit(uid, cs, dict(load), dict(values))

    units = []
    for key in sorted(by_group):
        cs = by_group[key]
        whole = unit_of(key, cs)
        if cabinet_relaxation_ok([whole], rules, True):
            units.append(whole)
            continue
        # The group can never sit in one cabinet under the current rules: split it into the fewest
        # chunks that each fit (cables sorted by class so A and B separate first) and raise a TQ.
        reasons = why_not_fit([whole], rules)
        chunks: List[List[Cable]] = []
        for c in sorted(cs, key=lambda c: (tuple(sorted(c.color.items())), -c.size, c.id)):
            for ch in chunks:
                if cabinet_relaxation_ok([unit_of("t", ch + [c])], rules, True):
                    ch.append(c)
                    break
            else:
                chunks.append([c])
        for i, ch in enumerate(chunks):
            units.append(unit_of(f"{key}#{i + 1}", ch))
        tqs.append({"id": f"TQ-CAP-{key}", "kind": "rule_conflict", "items": [c.id for c in cs],
                    "rules": ["R1-GROUP"] + sorted({m for w in reasons for m in re.findall(r"\bR\d+-[A-Z0-9]+\b", w)}),
                    "message": f"Group {key} cannot stay in one cabinet: it " + "; it ".join(reasons) +
                               f". Placed as {len(chunks)} parts in separate cabinets. Options: confirm the split, "
                               f"relax the spare rule for this group, or re-group the signals."})
    return units


def solver_params(rules, det_time: float) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    p = rules["solver"]
    mode = p.get("determinism", "single_thread")
    if mode == "interleave":            # experimental in OR-Tools; crashed on one model in 9.15 (see doc)
        s.parameters.num_workers = p["workers"]
        s.parameters.interleave_search = True
    elif mode == "single_thread":       # one worker + deterministic time limit = reproducible
        s.parameters.num_workers = 1
    else:                               # "fast": full parallel portfolio, not reproducible run to run
        s.parameters.num_workers = p["workers"]
    s.parameters.max_deterministic_time = det_time  # deterministic limit, not wall clock
    s.parameters.random_seed = p["seed"]
    return s


# ----------------------------------------------------------------------------------------------
# Greedy (used as hint and as the honest B1 baseline)
# ----------------------------------------------------------------------------------------------
def greedy_units(units: List[Unit], rules, conservative: bool = True) -> List[int]:
    """First-fit-decreasing of units into cabinets using the stage-1 relaxation as the fit test."""
    cabs: List[List[int]] = []
    assign = [-1] * len(units)
    order = sorted(range(len(units)), key=lambda i: (-units[i].total, units[i].id))
    for i in order:
        for j, members in enumerate(cabs):
            if cabinet_relaxation_ok([units[k] for k in members + [i]], rules, conservative):
                members.append(i)
                assign[i] = j
                break
        else:
            cabs.append([i])
            assign[i] = len(cabs) - 1
    return assign


def cabinet_relaxation_ok(us: List[Unit], rules, conservative: bool = True) -> bool:
    usable_bp = BP_PER_CAB - spare_baseplates(rules)
    total = sum(u.total for u in us)
    if bp_need(total) > usable_bp:
        return False
    if _cap_violation(us, rules):
        return False
    for r in rules["segregation"]:
        if not r["enabled"]:
            continue
        classes = r.get("classes")
        keys = classes if classes else sorted({k for u in us for (rid, k) in u.load if rid == r["id"]})
        loads = {k: sum(u.load.get((r["id"], k), 0) for u in us) for k in keys}
        if r["level"] == "cabinet" and sum(1 for v in loads.values() if v) > 1:
            return False
        if r["level"] == "cioc" and sum(-(-v // SLOTS_PER_CIOC) for v in loads.values()) > CIOC_PER_CAB:
            return False
        extra = bp_need(sum(u.load.get((r["id"], ""), 0) for u in us)) if conservative else 0
        if r["level"] in ("cioc", "baseplate") and sum(bp_need(v) for v in loads.values()) + extra > usable_bp:
            return False
    return True


def repair_hint(units: List[Unit], rules, prev_cab: Dict[str, int]) -> List[int]:
    """Revision warm start: keep every unit in its Rev A cabinet, evict the cheapest units from any
    cabinet that no longer fits, then first-fit evicted and new units (existing cabinets first)."""
    assign = [prev_cab.get(u.id, -1) for u in units]
    n_cab = max([a for a in assign if a >= 0], default=-1) + 1
    members = defaultdict(list)
    for i, a in enumerate(assign):
        if a >= 0:
            members[a].append(i)
    pending = [i for i, a in enumerate(assign) if a < 0]
    for j in range(n_cab):
        cur = sorted(members[j], key=lambda i: (sum(c.used for c in units[i].cables), units[i].id))
        while cur and not cabinet_relaxation_ok([units[i] for i in cur], rules, True):
            pending.append(cur.pop(0))          # evict the unit that disturbs the fewest signals
        members[j] = cur
    for i in sorted(pending, key=lambda i: (-units[i].total, units[i].id)):
        for j in range(n_cab + len(pending)):
            if cabinet_relaxation_ok([units[k] for k in members[j] + [i]], rules, True):
                members[j].append(i)
                assign[i] = j
                break
    return assign


# ----------------------------------------------------------------------------------------------
# Stage 1: units -> cabinets
# ----------------------------------------------------------------------------------------------
def stage1(units: List[Unit], rules, prev_cab: Optional[Dict[str, int]] = None,
           cuts: Optional[List[List[int]]] = None, n_cab_max: Optional[int] = None,
           fix_cabinets: Optional[int] = None, hint_assign: Optional[List[int]] = None,
           conservative: bool = True):
    """conservative=False: pure relaxation (its optimum is a valid lower bound on cabinets).
       conservative=True : each never-share class also gets whole baseplates of its own, which makes
                           the per-cabinet subproblem (stage 2/3) feasible in practice."""
    usable_bp = BP_PER_CAB - spare_baseplates(rules)
    hint = repair_hint(units, rules, prev_cab) if prev_cab else greedy_units(units, rules, conservative)
    M = n_cab_max or (max(hint) + 1)
    if prev_cab:
        M = max(M, max(prev_cab.values(), default=-1) + 2)
    m = cp_model.CpModel()
    x = {(i, j): m.NewBoolVar(f"x{i}_{j}") for i in range(len(units)) for j in range(M)}
    used = [m.NewBoolVar(f"used{j}") for j in range(M)]
    bp_vars = []
    for i in range(len(units)):
        m.AddExactlyOne(x[i, j] for j in range(M))
    for j in range(M):
        tot = sum(units[i].total * x[i, j] for i in range(len(units)))
        bp = m.NewIntVar(0, usable_bp, f"bp{j}")
        bp_vars.append(bp)
        m.Add(SLOTS_PER_BP * bp >= tot)
        m.Add(bp <= usable_bp * used[j])
        for r in rules["segregation"]:
            if not r["enabled"]:
                continue
            class_bp = []
            nc = []
            # classes may be None = ALL_DISTINCT: gather every value seen across units
            r_classes = r.get("classes") or sorted({k for u in units for (rid, k) in u.load if rid == r["id"]})
            for k in r_classes:
                ld = sum(units[i].load.get((r["id"], k), 0) * x[i, j] for i in range(len(units)))
                if r["level"] == "cabinet":
                    h = m.NewBoolVar("")
                    m.Add(ld == 0).OnlyEnforceIf(h.Not())
                    nc.append(h)
                elif r["level"] == "cioc":
                    n = m.NewIntVar(0, CIOC_PER_CAB, "")
                    m.Add(SLOTS_PER_CIOC * n >= ld)
                    nc.append(n)
                    b = m.NewIntVar(0, usable_bp, "")
                    m.Add(SLOTS_PER_BP * b >= ld)
                    class_bp.append(b)
                else:  # baseplate
                    b = m.NewIntVar(0, usable_bp, "")
                    m.Add(SLOTS_PER_BP * b >= ld)
                    class_bp.append(b)
            if r["level"] == "cabinet":
                m.Add(sum(nc) <= 1)
            elif r["level"] == "cioc":
                m.Add(sum(nc) <= CIOC_PER_CAB)
            if conservative and r["level"] in ("cioc", "baseplate"):
                ldn = sum(units[i].load.get((r["id"], ""), 0) * x[i, j] for i in range(len(units)))
                bn = m.NewIntVar(0, usable_bp, "")
                m.Add(SLOTS_PER_BP * bn >= ldn)
                class_bp.append(bn)
            if class_bp:                       # per rule: its classes need disjoint baseplates
                m.Add(bp >= sum(class_bp))
        # cabinet-level at_most_k: <= k distinct attribute values per used cabinet
        for r in rules.get("capacity", []):
            if not r.get("enabled", True) or r.get("level") != "cabinet":
                continue
            vals = sorted(_unit_values(units, r["id"]))
            present = []
            for v in vals:
                y = m.NewBoolVar("")
                for i in range(len(units)):
                    if units[i].values.get((r["id"], v), 0):
                        m.AddImplication(x[i, j], y)
                present.append(y)
            m.Add(sum(present) <= r["k"])
    for cut in cuts or []:
        for j in range(M):
            m.Add(sum(x[i, j] for i in cut) <= len(cut) - 1)
    # objective
    if prev_cab is None:
        for j in range(M - 1):
            m.Add(used[j] >= used[j + 1])                    # cabinets numbered without gaps
        order = sorted(range(len(units)), key=lambda i: (-units[i].total, units[i].id))
        for rank, i in enumerate(order):                     # classic bin-packing symmetry breaking
            for j in range(rank + 1, M):
                m.Add(x[i, j] == 0)
        if fix_cabinets is None:
            m.Minimize(sum(used))
        else:   # phase 2 "design for change": same cabinet count, spread free baseplates evenly
            m.Add(sum(used) == fix_cabinets)
            mx = m.NewIntVar(0, usable_bp, "maxbp")
            m.AddMaxEquality(mx, bp_vars)
            m.Minimize(mx)
        h = hint_assign or hint
        for i in range(len(units)):
            for j in range(M):
                m.AddHint(x[i, j], 1 if h[i] == j else 0)
        for j in range(M):
            m.AddHint(used[j], 1 if j in set(h) else 0)
    else:
        moved_cost = []
        for i, u in enumerate(units):
            pj = prev_cab.get(u.id)
            if pj is not None and pj < M:
                moved_cost.append((sum(c.used for c in u.cables)) * (1 - x[i, pj]))
            for j in range(M):
                m.AddHint(x[i, j], 1 if hint[i] == j else 0)
        for j in range(M):
            m.AddHint(used[j], 1 if j in set(hint) else 0)
        cab_cost = rules["solver"]["cabinet_cost_in_moves"]
        m.Minimize(sum(moved_cost) * 1 + cab_cost * sum(used))
    s = solver_params(rules, rules["solver"]["det_time_balance" if fix_cabinets is not None else "det_time_stage1"])
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if st == cp_model.INFEASIBLE:
            return None, {"status": "INFEASIBLE"}
        # anytime guarantee: the warm start is feasible by construction, never return nothing
        lb = s.BestObjectiveBound() if conservative is False else None
        return (list(hint_assign or hint) if (conservative or prev_cab) else None), \
            {"status": "WARM_START_FALLBACK", "objective": None, "bound": lb, "wall": s.WallTime()}
    assign = [next(j for j in range(M) if s.Value(x[i, j])) for i in range(len(units))]
    info = {"status": s.StatusName(st), "objective": s.ObjectiveValue(), "bound": s.BestObjectiveBound(),
            "wall": s.WallTime()}
    return assign, info


# ----------------------------------------------------------------------------------------------
# Stage 2: cables -> CIOC inside one cabinet (exact)
# ----------------------------------------------------------------------------------------------
def stage2(cables: List[Cable], rules, prev_cioc: Optional[Dict[str, int]] = None):
    usable_bp = BP_PER_CAB - spare_baseplates(rules)
    m = cp_model.CpModel()
    K = range(CIOC_PER_CAB)
    z = {(c.id, k): m.NewBoolVar("") for c in cables for k in K}
    for c in cables:
        m.AddExactlyOne(z[c.id, k] for k in K)

    def cable_values(c: Cable, rule) -> set:
        return {getattr(s, rule["attribute"]) for s in c.signals if getattr(s, rule["attribute"])}

    capacity_rules = [r for r in rules.get("capacity", []) if r.get("enabled", True)]
    cohesion_rules = [r for r in rules.get("cohesion", []) if r.get("enabled", True)]
    bps = []
    for k in K:
        load = sum(c.size * z[c.id, k] for c in cables)
        m.Add(load <= SLOTS_PER_CIOC)
        bp = m.NewIntVar(0, BP_PER_CIOC, f"bp{k}")
        m.Add(SLOTS_PER_BP * bp >= load)
        for r in rules["segregation"]:
            cls_bp = []
            if not r["enabled"] or r["level"] == "cabinet":
                continue
            classes = r.get("classes") or sorted({c.color.get(r["id"], "") for c in cables} - {""})
            if r["level"] == "cioc":
                has = {cl: m.NewBoolVar("") for cl in classes}
                for c in cables:
                    cl = c.color.get(r["id"], "")
                    if cl:
                        m.AddImplication(z[c.id, k], has[cl])
                m.Add(sum(has.values()) <= 1)
            else:  # baseplate-level: classes need their own baseplates inside the CIOC
                for cl in classes:
                    ld = sum(c.size * z[c.id, k] for c in cables if c.color.get(r["id"], "") == cl)
                    b = m.NewIntVar(0, BP_PER_CIOC, "")
                    m.Add(SLOTS_PER_BP * b >= ld)
                    cls_bp.append(b)
            if cls_bp:
                m.Add(bp >= sum(cls_bp))
        # cioc-level cohesion: every cable with a value sits in the same CIOC
        for r in cohesion_rules:
            if r["level"] != "cioc":
                continue
            vals = sorted({c.cohesion.get(r["id"], "") for c in cables if c.cohesion.get(r["id"], "")})
            for v in vals:
                has = []
                for kk in K:
                    h = m.NewBoolVar("")
                    for c in cables:
                        if c.cohesion.get(r["id"], "") == v:
                            m.AddImplication(z[c.id, kk], h)
                    has.append(h)
                m.Add(sum(has) <= 1)
        # cioc-level at_most_k on the values present in this CIOC
        for r in capacity_rules:
            if r["level"] != "cioc":
                continue
            vals = sorted({v for c in cables for v in cable_values(c, r)})
            present = []
            for v in vals:
                h = m.NewBoolVar("")
                for c in cables:
                    if v in cable_values(c, r):
                        m.AddImplication(z[c.id, k], h)
                present.append(h)
            m.Add(sum(present) <= r["k"])
        bps.append(bp)
    m.Add(sum(bps) <= usable_bp)
    if prev_cioc:
        cost = []
        for c in cables:
            pk = prev_cioc.get(c.id)
            if pk is not None:
                cost.append(c.used * (1 - z[c.id, pk]))
                m.AddHint(z[c.id, pk], 1)
        m.Minimize(sum(cost))
    else:
        mx = m.NewIntVar(0, BP_PER_CIOC, "mx")
        m.AddMaxEquality(mx, bps)
        m.Minimize(mx)          # spread spare baseplates over CIOCs (expansion room in each)
    s = solver_params(rules, rules["solver"]["det_time_stage2"])
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return ({c.id: next(k for k in K if s.Value(z[c.id, k])) for c in cables},
            [s.Value(b) for b in bps])


# ----------------------------------------------------------------------------------------------
# Stage 3: slots inside one CIOC
# ----------------------------------------------------------------------------------------------
def stage3(cables: List[Cable], rules, prev_start: Optional[Dict[str, int]] = None,
           bp_budget: int = BP_PER_CIOC) -> Optional[Dict[str, int]]:
    divisible = all(c.size in (2, 6, 12, 24) for c in cables)
    bp_rules = [r for r in rules["segregation"] if r["enabled"] and r["level"] == "baseplate"]
    baseplate_generic = any(
        x.get("enabled", True) and x.get("level") == "baseplate"
        for x in list(rules.get("cohesion", [])) + list(rules.get("capacity", [])))
    if divisible and not prev_start and not baseplate_generic:
        return _stage3_ffd(cables, bp_rules)
    return _stage3_cpsat(cables, rules, bp_rules, prev_start or {}, bp_budget)


def _stage3_ffd(cables: List[Cable], bp_rules) -> Optional[Dict[str, int]]:
    fill = [0] * BP_PER_CIOC
    cls_of_bp: List[Dict[str, str]] = [dict() for _ in range(BP_PER_CIOC)]
    starts = {}

    def compatible(b, c):
        return all(not c.color.get(r["id"], "") or cls_of_bp[b].get(r["id"], c.color[r["id"]]) == c.color[r["id"]]
                   for r in bp_rules)

    def mark(b, c):
        for r in bp_rules:
            if c.color.get(r["id"], ""):
                cls_of_bp[b][r["id"]] = c.color[r["id"]]

    for c in sorted(cables, key=lambda c: (-c.size, c.group, c.id)):
        if c.size == 24:
            b = next((b for b in range(BP_PER_CIOC - 1) if fill[b] == 0 and fill[b + 1] == 0), None)
            if b is None:
                return None
            fill[b] = fill[b + 1] = 12
            mark(b, c), mark(b + 1, c)
            starts[c.id] = b * SLOTS_PER_BP
        else:
            b = next((b for b in range(BP_PER_CIOC) if fill[b] + c.size <= SLOTS_PER_BP and compatible(b, c)), None)
            if b is None:
                return None
            starts[c.id] = b * SLOTS_PER_BP + fill[b]
            fill[b] += c.size
            mark(b, c)
    return starts


def _stage3_cpsat(cables, rules, bp_rules, prev_start, bp_budget=BP_PER_CIOC) -> Optional[Dict[str, int]]:
    m = cp_model.CpModel()
    st, iv, keep = {}, [], []
    bp_used = [m.NewBoolVar(f"bpu{b}") for b in range(BP_PER_CIOC)]
    for c in cables:
        s = m.NewIntVar(0, SLOTS_PER_CIOC - c.size, "")
        if c.size >= SLOTS_PER_BP or not rules["cable"]["small_may_straddle"]:
            b = m.NewIntVar(0, BP_PER_CIOC - 1, "")
            off = m.NewIntVar(0, max(0, SLOTS_PER_BP - c.size), "")
            m.Add(s == SLOTS_PER_BP * b + off)
            if c.size >= SLOTS_PER_BP:
                m.Add(off == 0)
            span = -(-c.size // SLOTS_PER_BP)
            for bb in range(BP_PER_CIOC):
                on = m.NewBoolVar("")
                m.Add(b == bb).OnlyEnforceIf(on)
                m.Add(b != bb).OnlyEnforceIf(on.Not())
                for d in range(span):
                    if bb + d < BP_PER_CIOC:
                        m.AddImplication(on, bp_used[bb + d])
        st[c.id] = s
        iv.append(m.NewIntervalVar(s, c.size, s + c.size, ""))
        if c.id in prev_start:
            k = m.NewBoolVar("")
            m.Add(s == prev_start[c.id]).OnlyEnforceIf(k)
            m.AddHint(s, prev_start[c.id])
            keep.append(c.used * k)
    m.AddNoOverlap(iv)
    m.Add(sum(bp_used) <= bp_budget)

    touch: Dict[Tuple[str, int], "cp_model.IntVar"] = {}

    def _touches(c, b):
        """Boolean: cable c overlaps baseplate b (created once, shared)."""
        key = (c.id, b)
        if key in touch:
            return touch[key]
        on = m.NewBoolVar("")
        m.Add(st[c.id] < (b + 1) * SLOTS_PER_BP).OnlyEnforceIf(on)
        m.Add(st[c.id] + c.size > b * SLOTS_PER_BP).OnlyEnforceIf(on)
        lo = m.NewBoolVar("")
        hi = m.NewBoolVar("")
        m.Add(st[c.id] >= (b + 1) * SLOTS_PER_BP).OnlyEnforceIf(lo)
        m.Add(st[c.id] + c.size <= b * SLOTS_PER_BP).OnlyEnforceIf(hi)
        m.AddBoolOr([on, lo, hi])
        touch[key] = on
        return on

    for r in bp_rules:  # never-share at baseplate level
        cls = sorted({c.color.get(r["id"], "") for c in cables} - {""})
        if len(cls) < 2:
            continue
        for b in range(BP_PER_CIOC):
            hb = {cl: m.NewBoolVar("") for cl in cls}
            for c in cables:
                cl = c.color.get(r["id"], "")
                if not cl:
                    continue
                m.AddImplication(_touches(c, b), hb[cl])
            m.Add(sum(hb.values()) <= 1)
    # baseplate-level cohesion: all cables of a value touch the same baseplate
    for r in [x for x in rules.get("cohesion", []) if x.get("enabled", True) and x["level"] == "baseplate"]:
        vals = sorted({c.cohesion.get(r["id"], "") for c in cables if c.cohesion.get(r["id"], "")})
        for v in vals:
            has = []
            for b in range(BP_PER_CIOC):
                h = m.NewBoolVar("")
                for c in cables:
                    if c.cohesion.get(r["id"], "") == v:
                        m.AddImplication(_touches(c, b), h)
                has.append(h)
            m.Add(sum(has) <= 1)
    # baseplate-level at_most_k: <= k distinct values on each baseplate
    for r in [x for x in rules.get("capacity", []) if x.get("enabled", True) and x["level"] == "baseplate"]:
        vals = sorted({getattr(sg, r["attribute"]) for c in cables for sg in c.signals
                       if getattr(sg, r["attribute"])})
        for b in range(BP_PER_CIOC):
            present = []
            for v in vals:
                h = m.NewBoolVar("")
                for c in cables:
                    if any(getattr(sg, r["attribute"]) == v for sg in c.signals):
                        m.AddImplication(_touches(c, b), h)
                present.append(h)
            m.Add(sum(present) <= r["k"])
    if keep:
        m.Maximize(sum(keep))
    s = solver_params(rules, 2.0)
    res = s.Solve(m)
    if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return {c.id: s.Value(st[c.id]) for c in cables}


# ----------------------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------------------
def allocate(signals: List[Signal], sizes: Dict[str, int], rules=DEFAULT_RULES,
             prev: Optional[Dict[str, Placement]] = None) -> dict:
    t0 = time.time()
    cables, tqs = build_cables(signals, sizes, rules)
    units = make_units(cables, rules, tqs)
    lbs = lower_bounds(cables, rules)
    prev_cab_unit = None
    if prev:
        prev_cab_unit = {}
        for u in units:
            cabs = [prev[c.id].cabinet for c in u.cables if c.id in prev]
            if cabs:
                prev_cab_unit[u.id] = max(set(cabs), key=cabs.count)
    cuts: List[List[int]] = []
    s1_info = {}
    lb_solver = None
    if prev is None:
        _, lb_info = stage1(units, rules, None, None, conservative=False)
        if lb_info.get("bound") is not None and lb_info.get("status") in ("OPTIMAL", "FEASIBLE", "WARM_START_FALLBACK"):
            lb_solver = int(math.ceil(lb_info["bound"] - 1e-6))
            lbs["solver_relaxation"] = lb_solver
            lbs["best"] = max(lbs["best"], lb_solver)
    for it in range(rules["solver"]["max_benders_iters"]):
        assign, s1_info = stage1(units, rules, prev_cab_unit, cuts)
        if assign is not None and prev is None and rules["solver"].get("design_for_change", True):
            k = len(set(assign))
            bal, bal_info = stage1(units, rules, None, cuts, n_cab_max=k, fix_cabinets=k, hint_assign=assign)
            if bal is not None:
                assign = bal
                s1_info["balance_status"] = bal_info["status"]
                s1_info["max_bp_per_cabinet"] = bal_info["objective"]
        if assign is None:
            return {"ok": False, "tqs": tqs + [{"id": "TQ-SOLVER", "kind": "capacity",
                                                  "message": f"Stage 1 returned {s1_info['status']}"}]}
        by_cab = defaultdict(list)
        for i, j in enumerate(assign):
            by_cab[j].append(i)
        placements: Dict[str, Placement] = {}
        failed = None
        # renumber cabinets densely (keeps Rev A numbering on revisions because prev cabinets come first)
        cab_ids = sorted(by_cab)
        renum = {j: (j if prev else n) for n, j in enumerate(cab_ids)}
        for j in cab_ids:
            cab_cables = [c for i in by_cab[j] for c in units[i].cables]
            prev_cioc = {c.id: prev[c.id].cioc for c in cab_cables
                         if prev and c.id in prev and prev[c.id].cabinet == j} if prev else None
            res2 = stage2(cab_cables, rules, prev_cioc)
            if res2 is None:
                failed = by_cab[j]
                break
            cio, budgets = res2
            for k in range(CIOC_PER_CAB):
                cc = [c for c in cab_cables if cio[c.id] == k]
                if not cc:
                    continue
                ps = {c.id: prev[c.id].start for c in cc
                      if prev and c.id in prev and prev[c.id].cabinet == j and prev[c.id].cioc == k} if prev else None
                starts = stage3(cc, rules, ps, budgets[k])
                if starts is None:
                    failed = by_cab[j]
                    break
                for c in cc:
                    placements[c.id] = Placement(renum[j], k, starts[c.id])
            if failed:
                break
        if failed is None:
            break
        cuts.append(failed)
    else:
        return {"ok": False, "tqs": tqs + [{"id": "TQ-SOLVER", "kind": "capacity", "message": "Benders loop did not converge"}]}
    rows = rows_from(cables, placements, rules.get("hardware_table"))
    n_cab = len({p.cabinet for p in placements.values()})
    return {"ok": True, "rows": rows, "placements": placements, "tqs": tqs, "cabinets": n_cab,
            "lower_bounds": lbs, "stage1": s1_info, "benders_cuts": len(cuts),
            "runtime_s": round(time.time() - t0, 2), "cables": cables}


# Hardware table lives in app/engine/hardware.py (PDS pairings, P1-4) and is
# shared with the solver, baselines and checker. The reference prototype's
# copy is intentionally NOT duplicated here.
from app.engine.hardware import hardware_for as _hw_for


def _hw(s, table=None) -> Tuple[Optional[str], Optional[str]]:
    return _hw_for(s.io_type, s.subtype, table)


def rows_from(cables: List[Cable], placements: Dict[str, Placement], hw_table=None) -> List[dict]:
    rows = []
    for c in cables:
        p = placements[c.id]
        by_pair = {s.pair: s for s in c.signals}
        for pair in range(1, c.size + 1):
            slot = p.start + pair - 1
            s = by_pair.get(pair)
            if s is None:
                charm, tb = "(spare position)", ""
            else:
                hw_c, hw_t = _hw(s, hw_table)
                charm, tb = (hw_c, hw_t) if hw_c else ("TBD - see TQ", "TBD - see TQ")
            rows.append({"tag": s.tag if s else "", "cable": c.id, "pair": pair,
                         "cabinet": p.cabinet + 1, "cioc": p.cioc + 1, "baseplate": slot // 12 + 1,
                         "slot": slot % 12 + 1, "charm": charm, "tb": tb,
                         "io_type": s.io_type if s else "", "subtype": s.subtype if s else "",
                         "group": c.group, "seg": s.seg if s else "", "voltage": s.voltage if s else ""})
    rows.sort(key=lambda r: (r["cabinet"], r["cioc"], r["baseplate"], r["slot"]))
    return rows


def count_moves(rows_a: List[dict], rows_b: List[dict], sig_a: List[Signal], sig_b: List[Signal]) -> dict:
    """Solver-induced moves: signals whose own data (cable, pair) did not change but whose position did."""
    pos_a = {r["tag"]: (r["cabinet"], r["cioc"], r["baseplate"], r["slot"]) for r in rows_a if r["tag"]}
    pos_b = {r["tag"]: (r["cabinet"], r["cioc"], r["baseplate"], r["slot"]) for r in rows_b if r["tag"]}
    key_a = {s.tag: (s.cable, s.pair) for s in sig_a}
    key_b = {s.tag: (s.cable, s.pair) for s in sig_b}
    common = [t for t in key_b if t in key_a and key_a[t] == key_b[t] and t in pos_a and t in pos_b]
    moved = [t for t in common if pos_a[t] != pos_b[t]]
    cab_moved = [t for t in moved if pos_a[t][0] != pos_b[t][0]]
    return {"unchanged_inputs": len(common), "moved": len(moved), "moved_cabinet": len(cab_moved),
            "cabinets_touched": sorted({pos_b[t][0] for t in moved} | {pos_a[t][0] for t in moved})}
