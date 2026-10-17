from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict
import time
from app.models.domain import Signal, Cable, AllocatedSlot, AllocResult, TQ
from app.models.rules import RuleSetConfig
from app.engine.naming import NameGenerator
from app.engine.hardware import HW_TABLE, hardware_for
from app.engine.solve.bridge import rules_to_ref


def _charm_and_tb(io_type, subtype):
    """Hardware from the data table; TBD placeholder when nothing matches."""
    charm_name, tb_name = hardware_for(io_type, subtype)
    if charm_name is None:
        return "TBD - see TQ", "TBD - see TQ"
    return charm_name, tb_name


def _verify(allocations, signals, cable_sizes, rules):
    """Independent check via backend/checker on row dicts (S2-7: honest)."""
    import checker.check as _chk
    from app.engine.io.template_writer import rows_from_allocations
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "",
                "seg": s.seg or ""} for s in signals]
    rows = rows_from_allocations(allocations)
    ref = rules_to_ref(rules)
    return _chk.check(io_rows, rows, ref, ref.get("hardware_table") or HW_TABLE, cable_sizes)


def _to_violations(found):
    from app.models.domain import Violation
    return [Violation(rule_id=v["rule"], rule_name=v["rule"], message=v["message"])
            for v in found if v["status"] == "violation"]

class BaselineEngine:
    def __init__(self, rules: RuleSetConfig):
        self.rules = rules
        self.name_gen = NameGenerator(rules.naming_patterns)

    def run_b0_file_order(self, signals: List[Signal], cable_sizes: Dict[str, int]) -> AllocResult:
        """
        B0 Baseline: Naive greedy in raw file order.
        Fills slots sequentially without respecting cable blocks or A/B segregation.
        """
        start_time = time.time()
        allocations: List[AllocatedSlot] = []

        cab = 0
        cioc = 0
        bp = 0
        slot = 0

        for s in signals:
            cab_name, cioc_name, bp_name = self.name_gen.get_names(cab, cioc, bp)

            # Lookup charm from the data table (P1-4)
            charm_name, tb_name = _charm_and_tb(s.io_type, s.subtype)

            alloc = AllocatedSlot(
                tag=s.tag,
                cable=s.cable,
                pair=s.pair,
                cabinet=cab,
                cioc=cioc,
                baseplate=bp,
                slot=slot,
                global_slot=cab * 384 + cioc * 96 + bp * 12 + slot,
                cabinet_name=cab_name,
                cioc_name=cioc_name,
                baseplate_name=bp_name,
                charm=charm_name,
                terminal_block=tb_name,
                io_type=s.io_type,
                subtype=s.subtype,
                group=s.group,
                seg=s.seg,
                is_spare=False
            )
            allocations.append(alloc)

            # Advance slot
            slot += 1
            if slot >= 12:
                slot = 0
                bp += 1
                if bp >= 8:
                    bp = 0
                    cioc += 1
                    if cioc >= 4:
                        cioc = 0
                        cab += 1

        cabinets_used = cab + 1 if allocations else 0
        found = _verify(allocations, signals, cable_sizes, self.rules)
        violations = _to_violations(found)
        runtime = time.time() - start_time

        lower_bound = max(1, (len(signals) + 344) // 345)

        return AllocResult(
            success=True,
            allocations=allocations,
            violations=violations,
            cabinets_used=cabinets_used,
            slots_used=len(allocations),
            total_slots_available=cabinets_used * 384,
            coverage_pct=100.0,
            spare_pct_actual=round(100.0 * (1.0 - len(allocations) / (cabinets_used * 384)), 1) if cabinets_used else 0.0,
            runtime_s=round(runtime, 3),
            lower_bound_cabinets=lower_bound,
            solver_status="GREEDY_B0"
        )

    def run_b1_grouped_ab(self, signals: List[Signal], cable_sizes: Dict[str, int]) -> AllocResult:
        """
        B1 Baseline: Heuristic greedy by group and A/B aware.
        Places cable blocks into CIOCs, but lacks global optimization.
        """
        start_time = time.time()
        
        # Build cable blocks
        cables_dict: Dict[str, Cable] = {}
        for s in signals:
            if s.cable not in cables_dict:
                size = cable_sizes.get(s.cable, 24 if s.pair > 12 else 12 if s.pair > 6 else 6 if s.pair > 2 else 2)
                cables_dict[s.cable] = Cable(id=s.cable, size=size, group=s.group)
            cables_dict[s.cable].signals.append(s)
            if s.seg:
                cables_dict[s.cable].segs.add(s.seg)

        cable_list = list(cables_dict.values())
        # Sort by group, then segregation
        cable_list.sort(key=lambda c: (c.group or "", sorted(list(c.segs))[0] if c.segs else ""))

        # State tracking: CIOCs
        # 1 Cabinet = 4 CIOCs (96 slots each)
        max_cab_cap = int(384 * (1.0 - (self.rules.spare_capacity.spare_percentage / 100.0)))
        
        # Grid of CIOC slot occupancies: (cab, cioc) -> current slot offset (0..96), train_seg (None, 'A', 'B')
        cioc_offset: Dict[Tuple[int, int], int] = defaultdict(int)
        cioc_train: Dict[Tuple[int, int], Optional[str]] = defaultdict(lambda: None)
        cab_used: Dict[int, int] = defaultdict(int)
        group_cab_map: Dict[str, int] = {}

        allocations: List[AllocatedSlot] = []

        for cbl in cable_list:
            cbl_seg = list(cbl.segs)[0] if cbl.segs else None
            cbl_grp = cbl.group

            # Target cabinet
            target_cab = None
            if cbl_grp and cbl_grp in group_cab_map:
                target_cab = group_cab_map[cbl_grp]

            placed = False
            # Try to place in target_cab first, or find new cabinet
            cabs_to_try = [target_cab] if target_cab is not None else list(range(100))

            for cab in cabs_to_try:
                if cab is None:
                    continue
                # Check cabinet capacity
                if cab_used[cab] + cbl.size > max_cab_cap:
                    continue

                # Try CIOCs in this cabinet
                for cioc in range(4):
                    curr_train = cioc_train[(cab, cioc)]
                    # Segregation check
                    if cbl_seg and curr_train and curr_train != cbl_seg:
                        continue

                    curr_off = cioc_offset[(cab, cioc)]
                    # Baseplate boundary alignment for 24 and 12-pair
                    aligned_off = curr_off
                    if cbl.size in [12, 24]:
                        if aligned_off % 12 != 0:
                            aligned_off += (12 - (aligned_off % 12))

                    if aligned_off + cbl.size <= 96:
                        # Place cable here!
                        if cbl_grp and cbl_grp not in group_cab_map:
                            group_cab_map[cbl_grp] = cab

                        if cbl_seg:
                            cioc_train[(cab, cioc)] = cbl_seg

                        sig_map = {s.pair: s for s in cbl.signals}
                        for p in range(1, cbl.size + 1):
                            slot_in_cioc = aligned_off + (p - 1)
                            bp = slot_in_cioc // 12
                            sl = slot_in_cioc % 12
                            cab_name, cioc_name, bp_name = self.name_gen.get_names(cab, cioc, bp)

                            s = sig_map.get(p)
                            if s:
                                charm_name, tb_name = _charm_and_tb(s.io_type, s.subtype)

                                alloc = AllocatedSlot(
                                    tag=s.tag,
                                    cable=s.cable,
                                    pair=p,
                                    cabinet=cab,
                                    cioc=cioc,
                                    baseplate=bp,
                                    slot=sl,
                                    global_slot=cab * 384 + cioc * 96 + bp * 12 + sl,
                                    cabinet_name=cab_name,
                                    cioc_name=cioc_name,
                                    baseplate_name=bp_name,
                                    charm=charm_name,
                                    terminal_block=tb_name,
                                    io_type=s.io_type,
                                    subtype=s.subtype,
                                    group=s.group,
                                    seg=s.seg,
                                    is_spare=False
                                )
                            else:
                                alloc = AllocatedSlot(
                                    tag=None,
                                    cable=cbl.id,
                                    pair=p,
                                    cabinet=cab,
                                    cioc=cioc,
                                    baseplate=bp,
                                    slot=sl,
                                    global_slot=cab * 384 + cioc * 96 + bp * 12 + sl,
                                    cabinet_name=cab_name,
                                    cioc_name=cioc_name,
                                    baseplate_name=bp_name,
                                    charm="SPARE CHARM",
                                    terminal_block="SPARE TB",
                                    is_spare=True
                                )
                            allocations.append(alloc)

                        cioc_offset[(cab, cioc)] = aligned_off + cbl.size
                        cab_used[cab] += cbl.size
                        placed = True
                        break

                if placed:
                    break

        cabinets_used = max([s.cabinet for s in allocations], default=-1) + 1
        # S2-7: cables B1 could not place are reported, never silently dropped.
        placed_cables = {s.cable for s in allocations if not s.is_spare}
        unplaced = [c for c in cable_list if c.id not in placed_cables]
        unplaced_tags = [s.tag for c in unplaced for s in c.signals]
        tqs = []
        if unplaced:
            tqs.append(TQ(id="TQ-B1-UNPLACED", kind="capacity",
                          items=sorted(unplaced_tags), tags=sorted(unplaced_tags),
                          rows=[], rule_ids=["R3-CAPACITY"],
                          message=f"B1 greedy could not place {len(unplaced)} cable(s) "
                                  f"({len(unplaced_tags)} signals) under the rules; "
                                  f"cables: {', '.join(c.id for c in unplaced[:5])}"
                                  f"{'...' if len(unplaced) > 5 else ''}.",
                          options=["Use the CHARMSAT engine, or relax the spare rule."]))
        found = _verify(allocations, signals, cable_sizes, self.rules)
        violations = _to_violations(found)
        runtime = time.time() - start_time
        lower_bound = max(1, (len(signals) + 344) // 345)
        placed_tags = {s.tag for s in allocations if s.tag}
        input_tags = {s.tag for s in signals}
        coverage = round(100.0 * len(placed_tags & input_tags) / max(1, len(input_tags)), 1)

        return AllocResult(
            success=len(violations) == 0,
            allocations=allocations,
            tqs=tqs,
            violations=violations,
            cabinets_used=cabinets_used,
            slots_used=len([s for s in allocations if not s.is_spare]),
            total_slots_available=cabinets_used * 384,
            coverage_pct=coverage,
            spare_pct_actual=round(100.0 * (1.0 - len(allocations) / (cabinets_used * 384)), 1) if cabinets_used else 0.0,
            runtime_s=round(runtime, 3),
            lower_bound_cabinets=lower_bound,
            solver_status="GREEDY_B1"
        )
