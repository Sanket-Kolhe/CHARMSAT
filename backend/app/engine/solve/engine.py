"""Three-stage allocation engine (P2-1) + revision with keep literals (P2-2 core).

solve_allocation: repo Signals -> AllocResult (+ core placements for later
revisions). solve_revision: Rev B with keep literals, a from-scratch
baseline for contrast, and a MoveRecord per moved signal. Forcing-rule
attribution per move is P4-2; until then the field is empty (never guessed).
"""
import time
from typing import Dict, List, Optional, Tuple

from app.models.domain import AllocResult, RevisionSummary, RevisionMoveDetail
from app.models.rules import RuleSetConfig
from app.engine.solve import core
from app.engine.solve.bridge import (
    rules_to_ref, to_core_signals, build_alloc_result,
)

# core cable_id -> (cabinet, cioc, start), 0-based; feeds keep literals.
PrevMap = Dict[str, Tuple[int, int, int]]


def _to_prev(placements: Dict[str, "core.Placement"]) -> PrevMap:
    return {cid: (p.cabinet, p.cioc, p.start) for cid, p in placements.items()}


def _from_prev(prev: PrevMap) -> Dict[str, "core.Placement"]:
    return {cid: core.Placement(cabinet=c, cioc=k, start=s) for cid, (c, k, s) in prev.items()}


def solve_allocation(signals, cable_sizes: Dict[str, int], rules: RuleSetConfig,
                     prev: Optional[PrevMap] = None) -> Tuple[AllocResult, PrevMap, dict]:
    """Returns (AllocResult, prev-map for revisions, raw core result)."""
    ref_rules = rules_to_ref(rules)
    core_sigs = to_core_signals(signals)
    row_lookup = {s.tag: s.row_no for s in signals}
    t0 = time.time()
    res = core.allocate(core_sigs, dict(cable_sizes), ref_rules,
                        prev=_from_prev(prev) if prev else None)
    res["runtime_s"] = round(time.time() - t0, 2)
    out = build_alloc_result(res, rules, row_lookup)
    return out, _to_prev(res.get("placements", {})), res


def _move_kind(a, b) -> str:
    if a[0] != b[0]:
        return "cabinet"
    if a[1] != b[1]:
        return "cioc"
    return "slot"


def _same_unit(level: str, row: dict, pos: tuple) -> bool:
    if level == "cabinet":
        return row["cabinet"] == pos[0]
    if level == "cioc":
        return (row["cabinet"], row["cioc"]) == (pos[0], pos[1])
    return (row["cabinet"], row["cioc"], row["baseplate"]) == (pos[0], pos[1], pos[2])


def attribute_forcing_rule(tag, pos_a, pos_b, io_a, io_b, rows_a, rows_b, rules) -> tuple:
    """Which rule blocks this signal's Rev A slot under Rev B data (P4-2).

    Deterministic, and honest: when no rule conflict is demonstrable at the old
    slot the move is reported as an optimiser rebalance, never guessed.
    Returns (rule_id, reason).
    """
    ta, tb = io_a.get(tag), io_b.get(tag)
    if not ta or not tb:
        return "", "optimiser rebalance: signal added or removed"
    if (ta.cable, ta.pair) != (tb.cable, tb.pair):
        return "RULE-02", f"cable/pair changed for {tag} in Rev B"
    if (ta.io_type, ta.subtype or "") != (tb.io_type, tb.subtype or ""):
        return "RULE-06", f"IO type/subtype changed for {tag} in Rev B"
    pairs_a = {s.pair for s in io_a.values() if s.cable == ta.cable}
    pairs_b = {s.pair for s in io_b.values() if s.cable == tb.cable}
    if pairs_a != pairs_b:
        return "RULE-02", (f"cable {tb.cable} block changed ({len(pairs_a)}→{len(pairs_b)} pairs); "
                           f"the whole block shifted to stay contiguous")
    ref = rules_to_ref(rules)
    for r in ref["segregation"]:
        if not r["enabled"]:
            continue
        attr, classes = r["attribute"], r.get("classes")
        tval = getattr(tb, attr) or ""
        if classes and tval not in classes:
            continue
        for row in rows_b:
            if not row["tag"] or row["tag"] == tag or not _same_unit(r["level"], row, pos_a):
                continue
            mval = getattr(io_b[row["tag"]], attr) or ""
            if classes and mval not in classes:
                continue
            if tval and mval and mval != tval:
                return r["id"], (f"the {r['level']} holding the old slot now mixes {mval} with {tval} "
                                 f"in Rev B (rule {r['id']})")
    if rules.group_cohesion.enabled and pos_a[0] != pos_b[0] and ta.group:
        cabs = {row["cabinet"] for row in rows_b if row["tag"] and io_b[row["tag"]].group == ta.group}
        if len(cabs) > 1:
            return "RULE-03", f"group {ta.group} now spans cabinets {sorted(cabs)} in Rev B"
    occupant = next((row for row in rows_b
                     if row.get("tag") and row["tag"] != tag
                     and (row["cabinet"], row["cioc"], row["baseplate"], row["slot"]) == pos_a), None)
    if occupant is not None:
        oc = io_b[occupant["tag"]]
        if oc.cable != tb.cable:
            return "RULE-02", (f"old slot now sits inside cable {oc.cable}'s contiguous block "
                               f"(blocks repacked to keep every cable whole)")
        return "RULE-02", (f"cable {tb.cable} block reordered in Rev B; the old slot carries "
                           f"pair {oc.pair} of the same cable")
    cabs_a = len({row["cabinet"] for row in rows_a if row["tag"]})
    cabs_b = len({row["cabinet"] for row in rows_b if row["tag"]})
    if cabs_b > cabs_a and pos_a[0] != pos_b[0]:
        return "RULE-04", f"Rev B needs {cabs_b} cabinets vs {cabs_a} in Rev A (spare/capacity repacked)"
    return "", "optimiser rebalance: no rule blocks the Rev A slot under Rev B data"


def solve_revision(signals_b, sizes_b: Dict[str, int], rules: RuleSetConfig,
                   prev: PrevMap, signals_a, rows_a: List[dict],
                   core_a) -> Tuple[AllocResult, PrevMap, dict]:
    """Rev B via keep literals + from-scratch baseline (both measured)."""
    ref_rules = rules_to_ref(rules)
    core_b = to_core_signals(signals_b)
    row_lookup_b = {s.tag: s.row_no for s in signals_b}

    t0 = time.time()
    res_b = core.allocate(core_b, dict(sizes_b), ref_rules, prev=_from_prev(prev))
    res_b["runtime_s"] = round(time.time() - t0, 2)
    if not res_b.get("ok"):
        out = build_alloc_result(res_b, rules, row_lookup_b)
        return out, {}, res_b

    res_s = core.allocate(core_b, dict(sizes_b), ref_rules)  # from scratch
    mv = core.count_moves(rows_a, res_b["rows"], core_a, core_b)
    ms = core.count_moves(rows_a, res_s["rows"], core_a, core_b)

    pos_a = {r["tag"]: (r["cabinet"], r["cioc"], r["baseplate"], r["slot"])
             for r in rows_a if r["tag"]}
    pos_b = {r["tag"]: (r["cabinet"], r["cioc"], r["baseplate"], r["slot"])
             for r in res_b["rows"] if r["tag"]}
    key_a = {s.tag: (s.cable, s.pair) for s in core_a}
    key_b = {s.tag: (s.cable, s.pair) for s in core_b}
    tags_a, tags_b = set(key_a), set(key_b)
    added = tags_b - tags_a
    deleted = tags_a - tags_b
    common = tags_a & tags_b
    changed = {t for t in common if key_a[t] != key_b[t]}
    new_by_tag = {r["tag"]: r for r in res_b["rows"] if r["tag"]}

    details: List[RevisionMoveDetail] = []
    moved_tags = [t for t in common - changed
                  if t in pos_a and t in pos_b and pos_a[t] != pos_b[t]]
    io_a = {s.tag: s for s in core_a}
    io_b = {s.tag: s for s in core_b}
    for t in sorted(moved_tags):
        a, b = pos_a[t], pos_b[t]
        kind = _move_kind(a, b)
        r = new_by_tag[t]
        rule_id, reason = attribute_forcing_rule(
            t, a, b, io_a, io_b, rows_a, res_b["rows"], rules)
        details.append(RevisionMoveDetail(
            tag=t, cable=r["cable"], io_type=r.get("io_type") or "",
            group=r.get("group") or None,
            old_location=f"CAB-{a[0]:02d} / CIOC-{a[1]} / BP-{a[2]} / S-{a[3]}",
            new_location=f"CAB-{b[0]:02d} / CIOC-{b[1]} / BP-{b[2]} / S-{b[3]}",
            forcing_rule=rule_id,
            reason=reason,
        ))

    out = build_alloc_result(res_b, rules, row_lookup_b)
    out.rev_summary = RevisionSummary(
        added_count=len(added), deleted_count=len(deleted),
        changed_count=len(changed), moved_count=len(details),
        unchanged_count=len(common - changed) - len(details),
        affected_cabinets=mv.get("cabinets_touched", []),
        moves_ours=len(details), moves_from_scratch=ms.get("moved", 0),
        moves_detail=details,
    )
    return out, _to_prev(res_b.get("placements", {})), res_b
