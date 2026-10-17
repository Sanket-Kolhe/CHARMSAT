import random
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
from app.models.domain import Signal, Cable

# Realistic instrument prefixes by type
TAG_PREFIXES = {
    "AI": ["TT", "PT", "FT", "LT", "AT", "PDT"],
    "AO": ["CV", "FV", "TV", "PV", "LV"],
    "DI": ["ZSH", "ZSL", "PSH", "PSL", "TSH", "LSH", "LSL"],
    "DO": ["XV", "SOV", "PUMP", "BLR", "ALM", "BCN", "HRN"]
}

DO_SUBTYPES = ["SOV", "horn", "beacon", "ISOLATED", None]

STANDARD_COLUMNS = [
    "Tag",
    "IO Type",
    "Subtype",
    "Cable",
    "Pair",
    "Cable Size",
    "Group",
    "Segregation"
]

FUZZY_COLUMN_VARIANTS = {
    "Tag": ["Tag", "TAG_NUMBER", "Instrument Tag", "TAG_NAME", "Signal Tag", "TAG"],
    "IO Type": ["IO Type", "Signal Type", "I/O_TYPE", "IO_CATEGORY", "Type", "CHANNEL_TYPE"],
    "Subtype": ["Subtype", "IO_Subtype", "Device_Type", "SubType", "EQUIP_TYPE"],
    "Cable": ["Cable", "Cable_ID", "Multicore_Ref", "CABLE_TAG", "Cable No", "CABLE"],
    "Pair": ["Pair", "Pair_No", "Pair_Index", "PAIR", "Core_Pair"],
    "Cable Size": ["Cable Size", "Pairs_Total", "Cable_Pairs", "CABLE_SIZE", "Capacity_Pairs"],
    "Group": ["Group", "Unit_Area", "Process_Group", "GROUP_ID", "Area"],
    "Segregation": ["Segregation", "Train", "Safety_Seg", "SEG_A_B", "Channel_Train"]
}

class SyntheticGenerator:
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)

    def generate_dataset(
        self,
        n_signals: int = 1000,
        io_mix: Optional[Dict[str, float]] = None,
        cable_size_weights: Optional[Dict[int, float]] = None,
        ab_seg_fraction: float = 0.35,
        inject_defects: bool = False,
        defect_types: Optional[List[str]] = None
    ) -> Tuple[List[Signal], List[Dict[str, Any]]]:
        """
        Generates realistic DeltaV synthetic signals structured into cables.
        Returns (signals, cable_meta_list)
        """
        self.rng.seed(self.seed)
        if io_mix is None:
            io_mix = {"AI": 0.35, "DI": 0.35, "DO": 0.20, "AO": 0.10}
        if cable_size_weights is None:
            cable_size_weights = {24: 0.25, 12: 0.35, 6: 0.25, 2: 0.15}

        cable_sizes = list(cable_size_weights.keys())
        cable_weights = list(cable_size_weights.values())

        # Generate group pool
        num_groups = max(2, n_signals // 60)
        groups = [f"GRP-{i+1:02d}_{area}" for i, area in enumerate([
            "REACT", "DISTIL", "FURNACE", "FEED", "UTILITY", "COMPR", "STORAGE", "EFFLUENT", "BOILER", "OFFGAS"
        ][:num_groups])]
        if len(groups) < num_groups:
            for i in range(len(groups), num_groups):
                groups.append(f"GRP-{i+1:02d}_UNIT")

        signals: List[Signal] = []
        cables_info: List[Dict[str, Any]] = []

        total_signals_target = n_signals
        current_signal_count = 0
        cable_seq = 100
        tag_no = 1000  # monotonic counter: tags are unique by construction (P1-5)

        while current_signal_count < total_signals_target:
            cable_id = f"CBL-{cable_seq}"
            cable_seq += 1
            size = self.rng.choices(cable_sizes, weights=cable_weights, k=1)[0]
            group = self.rng.choice(groups)
            
            # Segregation for this cable
            has_seg = self.rng.random() < ab_seg_fraction
            seg = self.rng.choice(["A", "B"]) if has_seg else None

            # Decide used pairs: between 50% and 100% of cable size
            # e.g. for size 24, typically 16-24 used; for 6, 4-6 used
            min_used = max(1, int(size * 0.6))
            used_pairs_count = self.rng.randint(min_used, size)
            if current_signal_count + used_pairs_count > total_signals_target:
                used_pairs_count = max(1, total_signals_target - current_signal_count)

            # Pick pair indices (pair order contiguous from 1..used_pairs_count)
            cable_signals = []
            for p in range(1, used_pairs_count + 1):
                # Pick IO type based on weights
                io_type = self.rng.choices(
                    list(io_mix.keys()),
                    weights=list(io_mix.values()),
                    k=1
                )[0]

                # Prefix & Tag (counter guarantees uniqueness; P1-5)
                prefix = self.rng.choice(TAG_PREFIXES[io_type])
                tag_no += 1
                tag = f"{prefix}-{tag_no}"

                # Subtype
                subtype = None
                if io_type == "DO":
                    sub = self.rng.choice(DO_SUBTYPES)
                    if sub:
                        subtype = sub
                        if sub in ["SOV", "beacon", "horn", "ISOLATED"]:
                            tag = f"{sub[:3].upper()}-{tag_no}"

                sig = Signal(
                    tag=tag,
                    io_type=io_type,
                    subtype=subtype,
                    cable=cable_id,
                    pair=p,
                    group=group,
                    seg=seg
                )
                cable_signals.append(sig)
                signals.append(sig)
                current_signal_count += 1

            cables_info.append({
                "cable_id": cable_id,
                "size": size,
                "used_pairs": used_pairs_count,
                "group": group,
                "seg": seg
            })

        # Inject Defects if requested
        if inject_defects:
            signals = self._inject_defects(signals, defect_types)

        return signals, cables_info

    def _inject_defects(self, signals: List[Signal], defect_types: Optional[List[str]] = None) -> List[Signal]:
        """Inject known adversarial defects for TQ verification"""
        if not defect_types:
            defect_types = ["blank_type", "duplicate_tag", "pair_overflow", "ab_mixed_cable", "group_overflow"]

        sig_list = [s for s in signals] # shallow copy

        if "blank_type" in defect_types and len(sig_list) > 10:
            # Blank IO type
            target = sig_list[5]
            target.io_type = ""

        if "duplicate_tag" in defect_types and len(sig_list) > 20:
            # Duplicate Tag
            sig_list[15].tag = sig_list[14].tag

        if "pair_overflow" in defect_types and len(sig_list) > 30:
            # Pair number 30 in a smaller cable
            sig_list[25].pair = 48

        if "ab_mixed_cable" in defect_types and len(sig_list) > 40:
            # Cable carrying both A and B signals
            cbl_target = sig_list[35].cable
            matching = [s for s in sig_list if s.cable == cbl_target]
            if len(matching) >= 2:
                matching[0].seg = "A"
                matching[1].seg = "B"

        if "group_overflow" in defect_types and len(sig_list) > 400:
            # Assign 420 signals to one single group (exceeds single cabinet 384 capacity)
            huge_group = "GRP-OVERFLOW_GIANT"
            for s in sig_list[:420]:
                s.group = huge_group

        return sig_list

    def generate_revision_b(
        self,
        rev_a_signals: List[Signal],
        add_pct: float = 0.05,     # 5% added
        del_pct: float = 0.02,     # 2% deleted
        type_change_pct: float = 0.015, # 1.5% type change
        recable_pct: float = 0.0,  # unused: re-cabling a signal to a fresh
                                   # single-pair `_MOD` cable is dishonest test
                                   # data (P1-5). Kept for API compatibility.
        cable_sizes: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[Signal], Dict[str, Any]]:
        """
        Generates realistic Rev B from Rev A (mirrors reference/generate_revision).
        Additions land on FREE (spare) pairs of existing cables when one is
        available, otherwise on new 6-pair cables. Cable sizes are carried in
        diff_summary["cable_sizes"] so callers never infer sizes per signal.
        Returns (rev_b_signals, diff_summary)
        """
        self.rng.seed(self.seed + 100)
        surviving_signals: List[Signal] = []
        deleted_tags = set()
        added_tags = set()
        type_changed_tags = set()

        # 1. Deletions
        num_delete = max(1, int(len(rev_a_signals) * del_pct))
        delete_indices = set(self.rng.sample(range(len(rev_a_signals)), num_delete))
        for idx, sig in enumerate(rev_a_signals):
            if idx in delete_indices:
                deleted_tags.add(sig.tag)
            else:
                # copy
                surviving_signals.append(Signal(
                    tag=sig.tag,
                    io_type=sig.io_type,
                    subtype=sig.subtype,
                    cable=sig.cable,
                    pair=sig.pair,
                    group=sig.group,
                    seg=sig.seg
                ))

        # 2. Type Changes
        num_type_changes = max(1, int(len(surviving_signals) * type_change_pct))
        type_change_indices = self.rng.sample(range(len(surviving_signals)), num_type_changes)
        for idx in type_change_indices:
            sig = surviving_signals[idx]
            old_type = sig.io_type
            new_type = "AO" if old_type == "AI" else "AI" if old_type == "AO" else "DO" if old_type == "DI" else "DI"
            sig.io_type = new_type
            type_changed_tags.add(sig.tag)

        # 3. Additions on free pairs (size-aware), else new 6-pair cables
        sizes: Dict[str, int] = dict(cable_sizes or {})
        for s in surviving_signals:
            sizes.setdefault(s.cable, 24 if s.pair > 12 else 12 if s.pair > 6 else 6 if s.pair > 2 else 2)
        used_pairs: Dict[str, set] = {}
        for s in surviving_signals:
            used_pairs.setdefault(s.cable, set()).add(s.pair)
        meta = {s.cable: (s.group, s.seg) for s in surviving_signals}

        num_add = max(1, int(len(rev_a_signals) * add_pct))
        groups = sorted({s.group for s in surviving_signals if s.group}) or ["GRP-01_EXP"]
        new_signals = []
        tag_no = 900000
        new_seq = 1
        cables_sorted = sorted(used_pairs)
        attempts = 0
        while len(new_signals) < num_add and attempts < num_add * 20:
            attempts += 1
            tag_no += 1
            io_type = self.rng.choice(["AI", "DI", "DO", "AO"])
            prefix = self.rng.choice(TAG_PREFIXES[io_type])
            tag = f"{prefix}-{tag_no}"
            if self.rng.random() < 0.6 and cables_sorted:
                cable_id = self.rng.choice(cables_sorted)
                free = [p for p in range(1, sizes[cable_id] + 1) if p not in used_pairs[cable_id]]
                if not free:
                    continue
                pair = free[0]
                group, seg = meta[cable_id]
            else:
                cable_id = f"CBL-NEW-{new_seq:02d}"
                if cable_id not in sizes:
                    sizes[cable_id] = 6
                    meta[cable_id] = (self.rng.choice(groups), self.rng.choice(["A", "B", None]))
                    used_pairs[cable_id] = set()
                    cables_sorted.append(cable_id)
                pair = len(used_pairs[cable_id]) + 1
                if pair > sizes[cable_id]:
                    new_seq += 1
                    continue
                if pair == sizes[cable_id]:
                    new_seq += 1
                group, seg = meta[cable_id]
            used_pairs[cable_id].add(pair)
            new_signals.append(Signal(
                tag=tag,
                io_type=io_type,
                subtype=None,
                cable=cable_id,
                pair=pair,
                group=group,
                seg=seg
            ))
            added_tags.add(tag)

        all_rev_b = surviving_signals + new_signals

        diff_summary = {
            "rev_a_count": len(rev_a_signals),
            "rev_b_count": len(all_rev_b),
            "added_count": len(added_tags),
            "deleted_count": len(deleted_tags),
            "type_changed_count": len(type_changed_tags),
            "recabled_count": 0,
            "added_tags": list(added_tags),
            "deleted_tags": list(deleted_tags),
            "type_changed_tags": list(type_changed_tags),
            "recabled_tags": [],
            "cable_sizes": sizes,
        }

        return all_rev_b, diff_summary

    def to_dataframe(
        self,
        signals: List[Signal],
        cables_info: Optional[List[Dict[str, Any]]] = None,
        fuzz_headers: bool = False
    ) -> pd.DataFrame:
        """Converts signal list to DataFrame, optionally fuzzing column headers"""
        cable_size_map = {}
        if cables_info:
            for c in cables_info:
                cable_size_map[c["cable_id"]] = c["size"]

        rows = []
        for s in signals:
            size = cable_size_map.get(s.cable, 24 if s.pair > 12 else 12 if s.pair > 6 else 6 if s.pair > 2 else 2)
            rows.append({
                "Tag": s.tag,
                "IO Type": s.io_type,
                "Subtype": s.subtype or "",
                "Cable": s.cable,
                "Pair": s.pair,
                "Cable Size": size,
                "Group": s.group or "",
                "Segregation": s.seg or ""
            })

        df = pd.DataFrame(rows)

        if fuzz_headers:
            # Rename columns to fuzzy variants and shuffle columns
            rename_map = {}
            for col in df.columns:
                if col in FUZZY_COLUMN_VARIANTS:
                    rename_map[col] = self.rng.choice(FUZZY_COLUMN_VARIANTS[col])
            df = df.rename(columns=rename_map)
            # Reorder columns randomly
            shuffled_cols = list(df.columns)
            self.rng.shuffle(shuffled_cols)
            df = df[shuffled_cols]

        return df
