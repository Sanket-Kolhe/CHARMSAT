"""P1-2: mapper v2 - header variants, value sniffing, overrides applied."""
from app.engine.mapper import (
    ColumnAutoMapper, propose_mapping, apply_mapping, value_scores,
)
from app.engine.generator import FUZZY_COLUMN_VARIANTS


def _values_for(canonical: str, n: int = 12):
    """Plausible column values per canonical field."""
    if canonical == "Tag":
        return [f"TT-{1000 + i}" for i in range(n)]
    if canonical == "IO Type":
        return (["AI", "DI", "DO", "AO"] * ((n // 4) + 1))[:n]
    if canonical == "Subtype":
        return (["", "", "SOV", "horn"] * ((n // 4) + 1))[:n]
    if canonical == "Cable":
        return [f"CBL-{1 + i // 3}" for i in range(n)]
    if canonical == "Pair":
        return [str(1 + (i % 3)) for i in range(n)]
    if canonical == "Cable Size":
        return ["12"] * n
    if canonical == "Group":
        return [f"GRP-0{1 + i // 6}" for i in range(n)]
    if canonical == "Segregation":
        return (["A", "B", ""] * ((n // 3) + 1))[:n]
    return [""] * n


def test_all_fuzzy_variants_map():
    """Every recorded header variant maps to its canonical field."""
    mapper = ColumnAutoMapper()
    for canonical, variants in FUZZY_COLUMN_VARIANTS.items():
        for v in variants:
            res = mapper.map_columns([v])
            got = next(m.mapped_canonical for m in res.matches if m.detected_column == v)
            assert got == canonical, f"{v!r} -> {got!r}, want {canonical!r}"


def test_new_unseen_variants_map():
    """Variants never seen in training data (spaces, dots, caps)."""
    mapper = ColumnAutoMapper()
    for detected, want in [("TAG NO.", "Tag"), ("I/O Type", "IO Type"),
                           ("Multicore", "Cable"), ("PAIR", "Pair"),
                           ("Cable No", "Cable"), ("TAG_NO", "Tag")]:
        res = mapper.map_columns([detected])
        got = next(m.mapped_canonical for m in res.matches)
        assert got == want, f"{detected!r} -> {got!r}, want {want!r}"


def test_value_sniffing_beats_misleading_header():
    """A column with a type-sounding header ('Channel' matches IO Type, Pair
    and Segregation synonyms) but cable-code values must NOT map to any of
    them; the IO values in a junk-named column are still found."""
    header = ["Channel", "Remarks"]
    cols = [
        ["CBL-1", "CBL-1", "CBL-1", "CBL-2", "CBL-2", "CBL-2"],  # cable codes
        ["AI", "DI", "DO", "AO", "AI", "DI"],                    # io types
    ]
    res = propose_mapping(header, cols)
    got = {m.detected_column: m.mapped_canonical for m in res.matches}
    assert got["Channel"] not in ("IO Type", "Pair", "Segregation"), got
    assert got["Remarks"] == "IO Type", got
    remarks = next(m for m in res.matches if m.detected_column == "Remarks")
    assert "AI/AO/DI/DO" in remarks.evidence


def test_propose_mapping_messy_sheet():
    header = ["CABLE_TAG", "TAG_NAME", "Junk_Col", "CHANNEL_TYPE", "Pair_No",
              "Unit_Area", "Safety_Seg", "Cable_Pairs"]
    cols = [_values_for(c) if c != "Junk_Col" else ["x"] * 12
            for c in ["Cable", "Tag", "?", "IO Type", "Pair", "Group", "Segregation", "Cable Size"]]
    res = propose_mapping(header, cols)
    got = {m.detected_column: m.mapped_canonical for m in res.matches}
    assert got["CABLE_TAG"] == "Cable"
    assert got["TAG_NAME"] == "Tag"
    assert got["CHANNEL_TYPE"] == "IO Type"
    assert got["Pair_No"] == "Pair"
    assert got["Unit_Area"] == "Group"
    assert got["Safety_Seg"] == "Segregation"
    assert got["Cable_Pairs"] == "Cable Size"
    assert got["Junk_Col"] is None
    assert res.missing_required == []


def test_apply_mapping_override_changes_data():
    grid = [
        ["TAG_NAME", "CHANNEL_TYPE", "CABLE_TAG", "Pair_No"],
        ["TT-1", "AI", "CBL-1", "1"],
        ["TT-2", "DI", "CBL-1", "2"],
    ]
    # Engineer overrides: CHANNEL_TYPE is actually the tag column here? No:
    # override Cable <- TAG_NAME to prove the override is honoured.
    mapping = {"TAG_NAME": "Cable", "CHANNEL_TYPE": "IO Type",
               "CABLE_TAG": "Tag", "Pair_No": "Pair"}
    signals, sizes = apply_mapping(grid, 0, mapping)
    assert [s.tag for s in signals] == ["CBL-1", "CBL-1"]
    assert [s.cable for s in signals] == ["TT-1", "TT-2"]
    assert [s.row_no for s in signals] == [2, 3]


def test_apply_mapping_row_no_extra_and_sizes():
    grid = [
        ["Tag", "IO Type", "Cable", "Pair", "Cable Size", "Notes"],
        ["TT-1", "ai ", "CBL-1", "1", "12", "field note"],
        ["TT-2", "A.I.", "CBL-1", "2", "12", ""],
    ]
    mapping = {h: h for h in grid[0]}
    mapping["Notes"] = None  # IGNORE -> lands in Signal.extra
    signals, sizes = apply_mapping(grid, 0, mapping)
    assert signals[0].io_type == "AI"      # normalised ("ai ")
    assert signals[1].io_type == "AI"      # normalised ("A.I.")
    assert signals[0].row_no == 2
    assert signals[0].extra == {"Notes": "field note"}
    assert sizes == {"CBL-1": 12}
