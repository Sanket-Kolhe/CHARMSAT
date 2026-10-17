"""Bridge between the app (RuleSetConfig, repo Signals, AllocResult) and the
ported three-stage core (plain rules dicts, core Signals, row dicts).

The compiler here is the only place rule *kinds* are turned into the plain
structures the solver and the independent checker consume. Every generic rule
(custom_rules) flows through:

  relation "different" -> never-share (segregation) entry
  relation "same"      -> cohesion entry (attribute stays together per level)
  relation "at_most_k" -> capacity entry (<= k distinct values per level)

Adding another rule of an existing kind is a YAML edit; no code change.
"""
from typing import Dict, List, Optional, Tuple

from app.models.domain import AllocatedSlot, AllocResult, TQ
from app.models.rules import RuleSetConfig
from app.engine.naming import NameGenerator
from app.engine.solve import core

# Attribute -> the classes a "different" rule separates when none are given.
# seg has a fixed vocabulary; every other attribute is ALL_DISTINCT (None).
_DEFAULT_CLASSES = {"seg": ["A", "B"]}


def rules_to_ref(rules: RuleSetConfig) -> dict:
    """RuleSetConfig -> reference-style rules dict consumed by core stages."""
    segregation: List[dict] = []
    if rules.ab_segregation.enabled:
        segregation.append({
            "id": rules.ab_segregation.id, "attribute": "seg", "classes": ["A", "B"],
            "level": rules.ab_segregation.level, "enabled": True,
        })
    cohesion: List[dict] = []
    capacity: List[dict] = []
    for r in rules.custom_rules:
        if not r.enabled:
            continue
        if r.relation == "different":
            classes = r.classes if r.classes else _DEFAULT_CLASSES.get(r.attribute)
            segregation.append({
                "id": r.id, "attribute": r.attribute, "classes": classes,
                "level": r.level, "enabled": True,
            })
        elif r.relation == "same":
            cohesion.append({
                "id": r.id, "attribute": r.attribute, "level": r.level,
                "enabled": True,
            })
        else:  # at_most_k
            capacity.append({
                "id": r.id, "attribute": r.attribute, "level": r.level,
                "k": max(1, r.k_value), "enabled": True,
            })

    hardware_table = [h.model_dump() for h in rules.hardware_table] if rules.hardware_table else None
    return {
        "hardware": {"cabinet_ciocs": 4, "cioc_baseplates": 8, "baseplate_slots": 12},
        "hardware_table": hardware_table,
        "spare": {"percent": rules.spare_capacity.spare_percentage if rules.spare_capacity.enabled else 0.0,
                  "unit": "baseplate", "rounding": "ceil"},
        "group_cohesion": {"enabled": rules.group_cohesion.enabled,
                           "level": rules.group_cohesion.target_level,
                           "on_oversize": "split_with_tq"},
        "segregation": segregation,
        "cohesion": cohesion,
        "capacity": capacity,
        "cable": {"small_may_straddle": rules.cable_contiguity.allow_boundary_crossing_small,
                  "spare_pairs_occupy_slots": True},
        "solver": {"det_time_stage1": 3.0, "det_time_balance": 2.0, "det_time_stage2": 1.0,
                   "workers": 1, "seed": 7, "max_benders_iters": 8,
                   "cabinet_cost_in_moves": 200, "design_for_change": True,
                   "determinism": "single_thread"},
    }


def to_core_signals(signals) -> List["core.Signal"]:
    """Repo Signals -> core Signals (voltage from extra, default DC)."""
    return [core.Signal(tag=s.tag, io_type=s.io_type or "", subtype=s.subtype or "",
                        cable=s.cable or "", pair=s.pair, group=s.group or "",
                        seg=(s.seg or "").strip().upper(),
                        voltage=(s.extra.get("voltage", "DC") if s.extra else "DC"))
            for s in signals]


def tq_from_core(d: dict, row_lookup: Dict[str, int]) -> TQ:
    tags = list(d.get("items", []))
    rows = sorted({row_lookup[t] for t in tags if t in row_lookup})
    rules = list(d.get("rules", []))
    return TQ(id=d.get("id", "TQ-?"), kind=d.get("kind", "data"),
              items=tags, tags=tags, rows=rows,
              rule_ids=rules,
              message=d.get("message", ""),
              options=list(d.get("options", [])),
              mus=list(d.get("mus", rules)))


def alloc_row_to_slot(row: dict, names: NameGenerator) -> AllocatedSlot:
    """Core row (1-based addresses) -> AllocatedSlot (0-based + names)."""
    tag = row["tag"] or None
    cab, cioc, bp, sl = row["cabinet"] - 1, row["cioc"] - 1, row["baseplate"] - 1, row["slot"] - 1
    cab_name, cioc_name, bp_name = names.get_names(cab, cioc, bp)
    return AllocatedSlot(
        tag=tag, cable=row["cable"], pair=row["pair"],
        cabinet=cab, cioc=cioc, baseplate=bp, slot=sl,
        global_slot=cab * 384 + cioc * 96 + bp * 12 + sl,
        cabinet_name=cab_name, cioc_name=cioc_name, baseplate_name=bp_name,
        charm=row["charm"], terminal_block=row["tb"],
        io_type=row.get("io_type") or None, subtype=row.get("subtype") or None,
        group=row.get("group") or None, seg=row.get("seg") or None,
        is_spare=not tag,
    )


def build_alloc_result(res: dict, rules: RuleSetConfig,
                       row_lookup: Dict[str, int]) -> AllocResult:
    """Core allocate() dict -> AllocResult. ok=False becomes an honest failure."""
    names = NameGenerator(rules.naming_patterns)
    tqs = [tq_from_core(d, row_lookup) for d in res.get("tqs", [])]
    lbs = res.get("lower_bounds", {"best": 0})
    lb = int(lbs.get("best", 0))
    if not res.get("ok"):
        return AllocResult(success=False, allocations=[], tqs=tqs, violations=[],
                           cabinets_used=0, coverage_pct=0.0, lower_bound_cabinets=lb,
                           solver_status="INFEASIBLE_STAGE1", runtime_s=res.get("runtime_s", 0.0))
    slots = [alloc_row_to_slot(r, names) for r in res["rows"]]
    n_cab = res.get("cabinets", 0)
    st = res.get("stage1", {}).get("status", "FEASIBLE")
    status = "OPTIMAL" if st == "OPTIMAL" else "FEASIBLE"
    req_empty = core.spare_baseplates(rules_to_ref(rules))
    used_bp: Dict[int, set] = {}
    for a in slots:
        used_bp.setdefault(a.cabinet, set()).add((a.cioc, a.baseplate))
    empty_bp = {c: 32 - len(bps) for c, bps in used_bp.items()}
    return AllocResult(
        success=True, allocations=slots, tqs=tqs, violations=[],
        cabinets_used=n_cab,
        slots_used=len([s for s in slots if not s.is_spare]),
        total_slots_available=n_cab * 384,
        coverage_pct=100.0,
        spare_pct_actual=round(100.0 * (1.0 - len(slots) / (n_cab * 384)), 1) if n_cab else 0.0,
        runtime_s=res.get("runtime_s", 0.0),
        lower_bound_cabinets=lb,
        solver_status=status,
        bounds={k: int(v) for k, v in lbs.items() if isinstance(v, (int, float))},
        empty_bp_per_cabinet=empty_bp,
        required_empty_bp=req_empty,
    )
