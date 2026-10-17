"""Validator v2 (P1-3): every data trap in blueprint 10.2 becomes a TQ.

Returns (signals_ok, tqs, ledger) where ledger maps every input tag to
"placed" or "held:<TQ-id>". TQ items carry ALL affected tags (never [:10])
plus Excel row numbers. IO types/subtypes are normalised through the
synonym tables; text that matches nothing becomes a hardware TQ (the
position is still reserved, per reference/build_cables).
"""
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
from app.models.domain import Signal, TQ
from app.engine.mapper import normalise_io_type
from app.engine.hardware import normalise_subtype, HW_TABLE

GIANT_CABLE_PAIRS = 96  # a cable bigger than one CIOC cannot be placed


def _tq(tq_id: str, kind: str, tags: List[str], rows: List[int],
        rules: List[str], message: str, options: List[str] = [],
        mus: Optional[List[str]] = None) -> TQ:
    items = sorted(set(tags))
    return TQ(id=tq_id, kind=kind, items=items, tags=items,
              rows=sorted(set(rows)), rule_ids=rules, message=message,
              options=list(options), mus=list(mus if mus is not None else rules))


class DataValidator:
    def __init__(self, spare_pct: float = 10.0, max_cabinet_slots: int = 384):
        self.spare_pct = spare_pct
        self.max_cabinet_slots = max_cabinet_slots
        self.effective_cabinet_capacity = int(max_cabinet_slots * (1.0 - (spare_pct / 100.0)))

    def validate(self, signals: List[Signal],
                 cable_sizes: Dict[str, int]) -> Tuple[List[Signal], List[TQ], Dict[str, str]]:
        tqs: List[TQ] = []
        held: Dict[str, str] = {}   # tag -> tq id
        held_rows: Dict[str, List[int]] = defaultdict(list)

        def hold(tag: str, row: int, tq_id: str):
            held[tag] = tq_id
            held_rows[tag].append(row)

        # 0. Normalise IO type / subtype through synonym tables (S1-9).
        # Canonical subtypes (HIGH_CURRENT/RELAY/"") so the solver, the
        # workbook and the independent checker all compare the same words.
        # Unknown subtype text is left raw -> hardware TQ downstream.
        for s in signals:
            norm = normalise_io_type(s.io_type) if s.io_type else None
            if norm:
                s.io_type = norm
            sub = normalise_subtype(s.subtype)
            if sub is not None:
                s.subtype = sub or None

        # 1. Duplicate tags: both rows held (reference behaviour).
        seen: Dict[str, Signal] = {}
        for s in signals:
            if s.tag in seen:
                first = seen[s.tag]
                tq_id = f"TQ-DUP-{s.tag}"
                hold(s.tag, s.row_no, tq_id)
                hold(first.tag, first.row_no, tq_id)
            else:
                seen[s.tag] = s
        for tag, first in seen.items():
            if tag in held:
                tqs.append(_tq(f"TQ-DUP-{tag}", "data", [tag],
                               held_rows[tag] + [first.row_no],
                               ["RULE-UNIQUE-TAG"],
                               f"Tag {tag} appears twice; both rows held until the duplicate is corrected.",
                               ["Correct the duplicated tag in the IO list and re-upload."]))

        # 2. Blank / unknown IO type -> hardware TQ, position reserved.
        for s in signals:
            if s.tag in held:
                continue
            if not s.io_type or not normalise_io_type(s.io_type):
                tq_id = "TQ-DAT-01"
                tqs.append(_tq(tq_id, "data", [s.tag], [s.row_no], ["RULE-06"],
                               f"Signal {s.tag} (row {s.row_no}): missing or unknown IO type "
                               f"'{s.io_type}'. Position reserved; assign a valid type.",
                               ["Enter a valid IO type (AI/AO/DI/DO/RTD/TC) and re-upload."]))
                # reserved, not held: solver places a TBD CHARM (P1-4)

        # 3. Missing cable (blank): hold unless allow_missing_cable (default off).
        for s in signals:
            if s.tag in held or s.cable:
                continue
            tq_id = f"TQ-CABLE-{s.tag}"
            hold(s.tag, s.row_no, tq_id)
            tqs.append(_tq(tq_id, "data", [s.tag], [s.row_no], ["R4-CABLE-BLOCK"],
                           f"Signal {s.tag} (row {s.row_no}) has no cable reference and is held.",
                           ["Assign the signal to a cable, or enable cable_block.allow_missing_cable."]))

        # Group rows per cable for cable-level checks.
        by_cable: Dict[str, List[Signal]] = defaultdict(list)
        for s in signals:
            if s.tag not in held and s.cable:
                by_cable[s.cable].append(s)

        # 4. Pair out of range / duplicate (cable, pair): whole cable held (S1-7).
        for cid in sorted(by_cable):
            sigs = sorted(by_cable[cid], key=lambda s: (s.pair, s.tag))
            size = cable_sizes.get(cid, 0)
            if not size:
                pairs = [s.pair for s in sigs if s.pair >= 1]
                size = next((k for k in (2, 6, 12, 24, 48) if k >= max(pairs, default=0)), 0)
            bad = [s for s in sigs if s.pair < 1 or (size and s.pair > size)]
            seen_pair: Set[int] = set()
            dup: List[Signal] = []
            for s in sigs:
                if s.pair in seen_pair:
                    dup.append(s)
                seen_pair.add(s.pair)
            if bad or dup or size == 0:
                tq_id = f"TQ-PAIR-{cid}"
                for s in sigs:
                    hold(s.tag, s.row_no, tq_id)
                detail = sorted({s.pair for s in bad + dup})
                tqs.append(_tq(tq_id, "data", [s.tag for s in sigs],
                               [s.row_no for s in sigs], ["RULE-02"],
                               f"Cable {cid} (size {size or 'unknown'}): pair numbers out of range "
                               f"or used twice {detail}. Cable held until corrected.",
                               ["Correct the pair numbers so each pair 1..size appears once."]))

        # 5. Unknown subtype (no hardware-table match): TQ-HW, position reserved.
        for s in signals:
            if s.tag in held or not s.io_type:
                continue
            if normalise_subtype(s.subtype) is None:
                tqs.append(_tq(f"TQ-HW-{s.tag}", "data", [s.tag], [s.row_no], ["R6-HW"],
                               f"Signal {s.tag} (row {s.row_no}): subtype '{s.subtype}' matches no "
                               f"hardware-table row for {s.io_type}. Position reserved with TBD CHARM.",
                               ["Correct the subtype, or add a hardware-table row (P3)."]))

        # 6. Cable carrying several groups: follows majority; TQ lists others.
        for cid in sorted(by_cable):
            sigs = [s for s in by_cable[cid] if s.tag not in held]
            groups = {s.group for s in sigs if s.group}
            if len(groups) > 1:
                counts: Dict[str, int] = defaultdict(int)
                for s in sigs:
                    counts[s.group or ""] += 1
                majority = max(counts, key=lambda g: counts[g])
                minority = [s for s in sigs if (s.group or "") != majority]
                tqs.append(_tq(f"TQ-GRP-{cid}", "data", [s.tag for s in minority],
                               [s.row_no for s in minority], ["R1-GROUP"],
                               f"Cable {cid} carries signals of several groups {sorted(groups)}; "
                               f"it cannot be split so it follows group '{majority or '-'}'. "
                               f"{len(minority)} signal(s) may sit apart from their group.",
                               ["Confirm the cable follows the majority group, or re-group the signals."]))
                for s in sigs:
                    if not s.group:
                        continue
                    s.group = majority or s.group
                # re-point minority to majority for placement cohesion
                for s in minority:
                    s.group = majority

        # 7. Cable mixing A and B: unsatisfiable under R2+R4 -> hold cable.
        for cid in sorted(by_cable):
            sigs = [s for s in by_cable[cid] if s.tag not in held]
            segs = {(s.seg or "").strip().upper() for s in sigs} & {"A", "B"}
            if len(segs) > 1:
                tq_id = f"TQ-CONFLICT-{cid}"
                for s in sigs:
                    hold(s.tag, s.row_no, tq_id)
                tqs.append(_tq(tq_id, "rule_conflict", [s.tag for s in sigs],
                               [s.row_no for s in sigs], ["R2-AB", "R4-CABLE-BLOCK"],
                               f"Cable {cid} mixes {sorted(segs)}: never-share (R2-AB) and "
                               f"keep-cable-together (R4-CABLE-BLOCK) cannot both hold. "
                               f"Minimal conflict: R2-AB needs A and B in different units; "
                               f"R4-CABLE-BLOCK keeps this cable atomic. Cable held.",
                               ["Split the cable, or correct the segregation column."],
                               mus=["R2-AB", "R4-CABLE-BLOCK"]))

        # 8. Giant cable (> 1 CIOC): cannot be placed -> hold.
        for cid in sorted(by_cable):
            size = cable_sizes.get(cid, 0)
            sigs = [s for s in by_cable[cid] if s.tag not in held]
            if size > GIANT_CABLE_PAIRS and sigs:
                tq_id = f"TQ-CAP-{cid}"
                for s in sigs:
                    hold(s.tag, s.row_no, tq_id)
                tqs.append(_tq(tq_id, "capacity", [s.tag for s in sigs],
                               [s.row_no for s in sigs], ["R3-CAPACITY", "R4-CABLE-BLOCK"],
                               f"Cable {cid} has {size} pairs: bigger than one CIOC (96 slots). "
                               f"Minimal conflict: R3-CAPACITY limits a CIOC to 96 slots; "
                               f"R4-CABLE-BLOCK keeps this cable atomic. Cable held.",
                               ["Split the cable across two cable codes."],
                               mus=["R3-CAPACITY", "R4-CABLE-BLOCK"]))

        valid = [s for s in signals if s.tag not in held]
        ledger = {s.tag: ("held:" + held[s.tag] if s.tag in held else "placed") for s in signals}
        return valid, tqs, ledger
