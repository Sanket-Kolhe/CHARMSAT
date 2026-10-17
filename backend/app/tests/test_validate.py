"""P1-3: validator v2 - every data trap -> TQ with full tag lists + ledger."""
from app.engine.validator import DataValidator
from app.models.domain import Signal


def _sig(tag, io="AI", sub=None, cable="CBL-1", pair=1, group="G", seg="", row=0):
    return Signal(tag=tag, io_type=io, subtype=sub, cable=cable, pair=pair,
                  group=group, seg=seg, row_no=row)


def test_duplicate_cable_pair_holds_cable_with_full_lists():
    sigs = [_sig("T1", cable="C", pair=1, row=11),
            _sig("T2", cable="C", pair=1, row=12),   # dup pair
            _sig("T3", cable="C", pair=2, row=13)]
    valid, tqs, ledger = DataValidator().validate(sigs, {"C": 6})
    ids = [t.id for t in tqs]
    assert ids == ["TQ-PAIR-C"]
    tq = tqs[0]
    assert sorted(tq.tags) == ["T1", "T2", "T3"]     # ALL tags, never [:10]
    assert sorted(tq.rows) == [11, 12, 13]           # Excel provenance
    assert valid == []                               # whole cable held
    assert all(v.startswith("held:") for v in ledger.values())


def test_unknown_subtype_reserves_with_hw_tq():
    sigs = [_sig("Q1", io="DO", sub="QUANTUM", row=5)]
    valid, tqs, ledger = DataValidator().validate(sigs, {})
    assert [t.id for t in tqs] == ["TQ-HW-Q1"]
    assert [s.tag for s in valid] == ["Q1"]          # position reserved
    assert ledger == {"Q1": "placed"}


def test_ab_mixed_cable_held_with_conflict_tq():
    sigs = [_sig("A1", seg="A", cable="C", pair=1, row=1),
            _sig("B1", seg="B", cable="C", pair=2, row=2)]
    valid, tqs, ledger = DataValidator().validate(sigs, {"C": 2})
    assert [t.id for t in tqs] == ["TQ-CONFLICT-C"]
    assert tqs[0].kind == "rule_conflict"
    assert set(tqs[0].rule_ids) == {"R2-AB", "R4-CABLE-BLOCK"}
    assert valid == []


def test_multi_group_cable_follows_majority_with_tq():
    sigs = [_sig("G1", group="G1", cable="C", pair=1),
            _sig("G2", group="G1", cable="C", pair=2),
            _sig("X1", group="GX", cable="C", pair=3)]
    valid, tqs, ledger = DataValidator().validate(sigs, {"C": 12})
    assert [t.id for t in tqs] == ["TQ-GRP-C"]
    assert tqs[0].tags == ["X1"]
    assert all(s.group == "G1" for s in valid)       # follows majority


def test_missing_cable_held():
    sigs = [_sig("M1", cable="", row=9)]
    valid, tqs, ledger = DataValidator().validate(sigs, {})
    assert [t.id for t in tqs] == ["TQ-CABLE-M1"]
    assert valid == []
    assert ledger == {"M1": "held:TQ-CABLE-M1"}


def test_giant_cable_held():
    sigs = [_sig(f"T{i}", cable="BIG", pair=i + 1) for i in range(5)]
    valid, tqs, ledger = DataValidator().validate(sigs, {"BIG": 128})
    assert [t.id for t in tqs] == ["TQ-CAP-BIG"]
    assert tqs[0].kind == "capacity"
    assert valid == []


def test_type_normalisation_before_rules():
    sigs = [_sig("N1", io="ai ", pair=1, row=1), _sig("N2", io="A.I.", pair=2, row=2)]
    valid, tqs, ledger = DataValidator().validate(sigs, {"CBL-1": 6})
    assert tqs == []
    assert [s.io_type for s in valid] == ["AI", "AI"]


def test_ledger_covers_every_input_tag():
    sigs = [_sig("OK1", row=1), _sig("OK1", row=2),
            _sig("BAD", io="", row=3), _sig("M", cable="", row=4)]
    _, _, ledger = DataValidator().validate(sigs, {})
    assert set(ledger) == {"OK1", "BAD", "M"}
    assert ledger["OK1"].startswith("held:TQ-DUP-OK1")
    assert ledger["BAD"] == "placed"                 # reserved w/ TQ-DAT-01
    assert ledger["M"].startswith("held:")


def test_clean_file_no_tqs_all_placed():
    sigs = [_sig(f"T{i}", cable="C", pair=i + 1, row=i + 1) for i in range(6)]
    valid, tqs, ledger = DataValidator().validate(sigs, {"C": 6})
    assert tqs == []
    assert len(valid) == 6
    assert set(ledger.values()) == {"placed"}
