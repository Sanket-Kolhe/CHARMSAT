from typing import Dict, List, Optional, Tuple
from rapidfuzz import fuzz
from pydantic import BaseModel

CANONICAL_FIELDS = [
    "Tag",
    "IO Type",
    "Subtype",
    "Cable",
    "Pair",
    "Cable Size",
    "Group",
    "Segregation"
]

SYNONYM_DICTIONARY = {
    "Tag": [
        "tag", "tag_number", "instrument_tag", "tag_name", "signal_tag", "loop_tag",
        "tagno", "tag id", "tagname", "device_tag", "instrument tag no"
    ],
    "IO Type": [
        "io type", "signal type", "i/o type", "io_type", "type", "channel type",
        "io_category", "signal_category", "i/o", "io_desc", "signal"
    ],
    "Subtype": [
        "subtype", "sub_type", "io_subtype", "device_type", "equip_type",
        "equipment type", "load_type", "isolated_type", "feature"
    ],
    "Cable": [
        "cable", "cable_id", "multicore_ref", "cable_tag", "cable no", "multicore",
        "cable_number", "cable number", "cbl_id", "trunk_cable", "cable ref"
    ],
    "Pair": [
        "pair", "pair_no", "pair_index", "pair number", "core_pair", "pair_num",
        "channel_pair", "pair_id", "pair#"
    ],
    "Cable Size": [
        "cable size", "pairs_total", "cable_pairs", "cable_capacity", "size",
        "total_pairs", "cable cores", "cores", "capacity_pairs", "cable_size"
    ],
    "Group": [
        "group", "unit_area", "process_group", "group_id", "area", "unit",
        "subsystem", "plant_area", "section", "functional_group", "process_area"
    ],
    "Segregation": [
        "segregation", "train", "safety_seg", "seg_a_b", "channel_train",
        "train_id", "train_a_b", "seg", "segregation_class", "division", "train a/b"
    ]
}

class ColumnMatch(BaseModel):
    detected_column: str
    mapped_canonical: Optional[str] = None
    confidence_pct: float = 0.0
    alternative_matches: Dict[str, float] = {}
    evidence: str = ""  # why this mapping was proposed (P1-2)

class ColumnMappingResult(BaseModel):
    matches: List[ColumnMatch]
    unmapped_columns: List[str]
    missing_required: List[str]

class ColumnAutoMapper:
    def __init__(self, threshold: float = 50.0):
        self.threshold = threshold

    def _header_scores(self, file_columns: List[str]) -> Dict[Tuple[str, str], float]:
        """(column, canonical) -> 0..100 header fuzzy score."""
        import re as _re

        def clean(s: str) -> str:
            return _re.sub(r"\s+", " ", _re.sub(r"[_\-./]", " ", s.strip().lower())).strip()

        out = {}
        for col in file_columns:
            clean_col = clean(col)
            for canonical, synonyms in SYNONYM_DICTIONARY.items():
                best = fuzz.token_sort_ratio(clean_col, clean(canonical))
                for syn in synonyms:
                    best = max(best, fuzz.token_sort_ratio(clean_col, clean(syn)))
                out[(col, canonical)] = float(best)
        return out

    def map_columns(self, file_columns: List[str]) -> ColumnMappingResult:
        matches: List[ColumnMatch] = []
        assigned_canonicals = set()

        # Step 1: Compute match scores for each detected column against each canonical field
        candidate_scores: List[Tuple[float, str, str]] = []

        for col in file_columns:
            clean_col = col.strip().lower().replace("-", "_").replace(".", "")
            for canonical, synonyms in SYNONYM_DICTIONARY.items():
                best_score = 0.0
                # Direct match to canonical name
                canonical_score = fuzz.token_sort_ratio(clean_col, canonical.lower().replace("-", "_"))
                best_score = max(best_score, canonical_score)

                # Match against synonyms
                for syn in synonyms:
                    syn_score = fuzz.token_sort_ratio(clean_col, syn.replace("-", "_"))
                    if syn_score > best_score:
                        best_score = syn_score

                candidate_scores.append((best_score, col, canonical))

        # Sort candidate scores descending (greedy assignment)
        candidate_scores.sort(key=lambda x: x[0], reverse=True)

        col_assignments: Dict[str, Tuple[str, float]] = {}
        for score, col, canonical in candidate_scores:
            if col not in col_assignments and canonical not in assigned_canonicals:
                if score >= self.threshold:
                    col_assignments[col] = (canonical, round(score, 1))
                    assigned_canonicals.add(canonical)

        # Build results
        unmapped = []
        header_scores = self._header_scores(file_columns)
        for col in file_columns:
            alt_scores = {canon: round(header_scores[(col, canon)], 1) for canon in CANONICAL_FIELDS}

            if col in col_assignments:
                canon, conf = col_assignments[col]
                matches.append(ColumnMatch(
                    detected_column=col,
                    mapped_canonical=canon,
                    confidence_pct=conf,
                    alternative_matches=alt_scores
                ))
            else:
                unmapped.append(col)
                matches.append(ColumnMatch(
                    detected_column=col,
                    mapped_canonical=None,
                    confidence_pct=0.0,
                    alternative_matches=alt_scores
                ))

        # Required fields check
        required_fields = ["Tag", "IO Type", "Cable", "Pair"]
        missing_req = [req for req in required_fields if req not in assigned_canonicals]

        return ColumnMappingResult(
            matches=matches,
            unmapped_columns=unmapped,
            missing_required=missing_req
        )


# --------------------------------------------------------------------------------------
# P1-2: value sniffing + mapping applied to data
# --------------------------------------------------------------------------------------
IO_TYPE_WORDS = {
    "AI": "AI", "ANALOG INPUT": "AI", "ANALOGUE INPUT": "AI", "4-20MA IN": "AI",
    "AO": "AO", "ANALOG OUTPUT": "AO", "ANALOGUE OUTPUT": "AO", "4-20MA OUT": "AO",
    "DI": "DI", "DIGITAL INPUT": "DI", "DISCRETE INPUT": "DI",
    "DO": "DO", "DIGITAL OUTPUT": "DO", "DISCRETE OUTPUT": "DO",
    "RTD": "RTD", "TC": "TC",
}
IO_TYPE_VOCAB = set(IO_TYPE_WORDS) | {"AI", "AO", "DI", "DO", "RTD", "TC"}
SEG_WORDS = {"A": "A", "B": "B", "TRAIN A": "A", "TRAIN B": "B", "TRN-A": "A", "TRN-B": "B"}
STANDARD_SIZES = {2, 6, 12, 24, 48}


def _norm(v: str) -> str:
    return " ".join(str(v or "").strip().upper().split())


def _key(s: str) -> str:
    """Alphanumerics only, upper: 'A.I.'->'AI', 'Analog Input'->'ANALOGINPUT'."""
    import re as _re
    return _re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


_IO_KEYS = {_key(k): v for k, v in IO_TYPE_WORDS.items()}


def normalise_io_type(raw: str) -> Optional[str]:
    return _IO_KEYS.get(_key(raw))


def normalise_seg(raw: str) -> str:
    return SEG_WORDS.get(_norm(raw), "" if not _norm(raw) else _norm(raw))


def value_scores(values: List[str]) -> Tuple[Dict[str, float], Dict[str, str]]:
    """Score one column's values against each canonical field.

    Returns ({canonical: 0..100}, {canonical: evidence_text}). Pure function
    of the values, so a misleading header cannot outvote the data (P1-2).
    """
    vals = [v for v in (_norm(v) for v in values) if v]
    n = max(1, len(vals))
    scores: Dict[str, float] = {}
    ev: Dict[str, str] = {}

    io_hits = sum(1 for v in vals if _key(v) in _IO_KEYS)
    scores["IO Type"] = 100.0 * io_hits / n
    ev["IO Type"] = f"values look like AI/AO/DI/DO ({io_hits}/{n})"

    seg_hits = sum(1 for v in vals if v in SEG_WORDS or v in ("A", "B"))
    scores["Segregation"] = 100.0 * seg_hits / n
    ev["Segregation"] = f"values look like A/B segregation ({seg_hits}/{n})"

    pair_hits = 0
    for v in vals:
        try:
            pair_hits += 1 if 1 <= int(v) <= 48 else 0
        except ValueError:
            pass
    scores["Pair"] = 100.0 * pair_hits / n
    ev["Pair"] = f"values look like pair numbers 1-48 ({pair_hits}/{n})"

    size_hits = 0
    for v in vals:
        try:
            size_hits += 1 if int(v) in STANDARD_SIZES else 0
        except ValueError:
            pass
    scores["Cable Size"] = 100.0 * size_hits / n
    ev["Cable Size"] = f"values look like cable sizes 2/6/12/24 ({size_hits}/{n})"

    from collections import Counter
    counts = Counter(vals)
    distinct = set(vals)
    repeat = sum(c for c in counts.values() if c > 1) / n if vals else 0.0
    nonnum = sum(1 for v in vals if not v.replace(".", "", 1).isdigit()) / n
    # Code-like discount: values drawn from a tiny known vocabulary (IO
    # types A/B) are types, not cable/group/tag codes — even if repeated.
    vocab_frac = 0.0
    if distinct:
        in_vocab = sum(1 for v in distinct if _key(v) in _IO_KEYS or v in SEG_WORDS or v in ("A", "B"))
        vocab_frac = in_vocab / len(distinct)
    code_like = 1.0 - vocab_frac
    # Constant columns (1 distinct value) carry almost no value evidence;
    # the header must carry the mapping (still works: 0.6 * header).
    info = 0.25 if len(distinct) <= 1 and len(vals) >= 4 else 1.0
    scores["Cable"] = 100.0 * repeat * (0.5 + 0.5 * nonnum) * code_like * info
    ev["Cable"] = f"values repeat like cable codes ({repeat:.0%} repeated)"
    scores["Group"] = 100.0 * repeat * (0.5 + 0.5 * nonnum) * code_like * info
    ev["Group"] = f"values repeat like group codes ({repeat:.0%} repeated)"

    uniq = len(set(vals)) / n if vals else 0.0
    scores["Tag"] = 100.0 * uniq * nonnum * code_like * info
    ev["Tag"] = f"values look like unique tags ({uniq:.0%} unique)"
    scores["Subtype"] = 100.0 * (1.0 - uniq) * nonnum * code_like * info
    ev["Subtype"] = "values look like short subtype codes"
    return scores, ev


def propose_mapping(header_cells: List[str], column_values: List[List[str]],
                    threshold: float = 50.0) -> "ColumnMappingResult":
    """One-to-one assignment by combined score = 0.6*header + 0.4*values.

    column_values[i] holds the data values under header_cells[i].
    """
    mapper = ColumnAutoMapper(threshold=threshold)
    header = mapper._header_scores(header_cells)
    valued = [value_scores(col) for col in column_values]
    order = {c: n for n, c in enumerate(CANONICAL_FIELDS)}

    cands: List[Tuple[float, int, int, str, str]] = []  # (combined, col, field_order, canon, evidence)
    for i, col in enumerate(header_cells):
        vscores, vev = valued[i] if i < len(valued) else ({}, {})
        for canonical in CANONICAL_FIELDS:
            h = header.get((col, canonical), 0.0)
            v = vscores.get(canonical, 0.0)
            # Data veto: a header-only claim (low value score) is rejected when
            # the values strongly match a DIFFERENT field, unless the header
            # is an exact synonym hit (100). Values beat misleading headers.
            vmax_other = max((vscores.get(c, 0.0) for c in CANONICAL_FIELDS if c != canonical),
                             default=0.0)
            if v < 20 and vmax_other >= 70 and h < 100:
                continue
            combined = 0.6 * h + 0.4 * v
            if combined >= threshold and (h >= 40 or v >= 70):
                cands.append((combined, i, order[canonical], canonical,
                              f"header {h:.0f} + {vev.get(canonical, '')}"))
    cands.sort(key=lambda t: (-t[0], t[2], t[1]))

    assigned_cols: Dict[int, Tuple[str, float, str]] = {}
    used_canon = set()
    for score, i, _, canon, evid in cands:
        if i not in assigned_cols and canon not in used_canon:
            assigned_cols[i] = (canon, round(score, 1), evid)
            used_canon.add(canon)

    matches = []
    unmapped = []
    for i, col in enumerate(header_cells):
        if i in assigned_cols:
            canon, conf, evid = assigned_cols[i]
            matches.append(ColumnMatch(detected_column=col, mapped_canonical=canon,
                                       confidence_pct=conf, evidence=evid))
        else:
            unmapped.append(col)
            matches.append(ColumnMatch(detected_column=col, mapped_canonical=None,
                                       confidence_pct=0.0, evidence="no confident match"))
    required = ["Tag", "IO Type", "Cable", "Pair"]
    missing = [r for r in required if r not in used_canon]
    return ColumnMappingResult(matches=matches, unmapped_columns=unmapped, missing_required=missing)


def apply_mapping(grid: List[List[str]], header_idx: int,
                  mapping: Dict[str, Optional[str]],
                  two_row_header: bool = False) -> Tuple[list, Dict[str, int]]:
    """Convert the data grid into Signals using the confirmed mapping.

    mapping: detected header text -> canonical field (None = ignore).
    Returns (signals, cable_sizes). Unmapped columns land in Signal.extra so
    rules can reference them. Cable Size column feeds cable_sizes (first wins).
    """
    from app.models.domain import Signal
    from app.engine.io.reader import data_rows

    header = grid[header_idx]
    col_canon = [mapping.get(h) for h in header]
    rows = data_rows(grid, header_idx, two_row_header)

    raw_sizes: Dict[str, int] = {}
    prelim = []
    for excel_row, cells in rows:
        cells = list(cells) + [""] * (len(header) - len(cells))
        rec = {canon: cells[i].strip() for i, canon in enumerate(col_canon) if canon}
        extra = {header[i]: cells[i].strip() for i, canon in enumerate(col_canon)
                 if not canon and cells[i].strip()}
        prelim.append((excel_row, rec, extra))
        cable = rec.get("Cable", "")
        size_raw = rec.get("Cable Size", "")
        if cable and size_raw and cable not in raw_sizes:
            try:
                if int(float(size_raw)) > 0:
                    raw_sizes[cable] = int(float(size_raw))
            except ValueError:
                pass

    signals = []
    for excel_row, rec, extra in prelim:
        try:
            pair = int(float(rec.get("Pair", "") or 0))
        except ValueError:
            pair = 0
        io_norm = normalise_io_type(rec.get("IO Type", ""))
        signals.append(Signal(
            tag=rec.get("Tag", ""),
            io_type=io_norm or rec.get("IO Type", "").strip(),
            subtype=rec.get("Subtype", "").strip() or None,
            cable=rec.get("Cable", "").strip(),
            pair=pair,
            group=rec.get("Group", "").strip() or None,
            seg=normalise_seg(rec.get("Segregation", "")) or None,
            row_no=excel_row,
            extra=extra,
        ))
    return signals, raw_sizes
