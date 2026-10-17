"""P4: each Rev B move names its forcing rule, and conflict TQs carry a MUS."""
from app.models.domain import Signal
from app.models.rules import RuleSetConfig
from app.engine.validator import DataValidator
from app.engine.generator import SyntheticGenerator
from app.engine.solve.engine import solve_allocation, solve_revision, attribute_forcing_rule
from app.engine.solve.bridge import to_core_signals

KNOWN_RULES = {"RULE-01", "RULE-02", "RULE-03", "RULE-04", "RULE-05", "RULE-06"}


def _sig(tag, io="AI", sub=None, cable="CBL-1", pair=1, group="G", seg="", row=0):
    return Signal(tag=tag, io_type=io, subtype=sub, cable=cable, pair=pair,
                  group=group, seg=seg, row_no=row)


def test_ab_conflict_tq_carries_mus_and_plain_wording():
    sigs = [_sig("A1", seg="A", cable="C", pair=1, row=1),
            _sig("B1", seg="B", cable="C", pair=2, row=2)]
    _valid, tqs, _ledger = DataValidator().validate(sigs, {"C": 2})
    tq = next(t for t in tqs if t.kind == "rule_conflict")
    assert set(tq.mus) == {"R2-AB", "R4-CABLE-BLOCK"}
    assert "Minimal conflict" in tq.message


def _run_revision(seed=42, n=1000):
    gen = SyntheticGenerator(seed=seed)
    sig, ci = gen.generate_dataset(n_signals=n)
    sizes = {c["cable_id"]: c["size"] for c in ci}
    rules = RuleSetConfig()
    valid_a, _, _ = DataValidator().validate(sig, sizes)
    _a, prev_a, raw_a = solve_allocation(valid_a, sizes, rules)
    sig_b, meta = gen.generate_revision_b(sig, cable_sizes=sizes)
    sizes_b = meta["cable_sizes"]
    valid_b, _, _ = DataValidator().validate(sig_b, sizes_b)
    _b, _, _ = solve_revision(valid_b, sizes_b, rules, prev_a, sig,
                              raw_a["rows"], to_core_signals(sig))
    return _b.rev_summary


def test_every_move_names_a_known_rule_or_is_honest():
    moves = _run_revision().moves_detail
    assert moves, "expected the fixture to require some moves"
    for m in moves:
        assert m.reason, f"{m.tag} has no reason"
        assert m.forcing_rule in KNOWN_RULES or m.forcing_rule == "", f"{m.tag}: {m.forcing_rule!r}"
        if not m.forcing_rule:
            assert "optimiser" in m.reason.lower()


def test_cable_block_growth_forces_moves_named_rule_02():
    moves = _run_revision().moves_detail
    named = [m for m in moves if m.forcing_rule == "RULE-02"]
    assert named, "cable-growth revision should move signals and name RULE-02"
    assert any("cable" in m.reason.lower() for m in named)


def test_attribution_helper_detects_segregation_conflict():
    rules = RuleSetConfig()
    io_a = {"T": _sig("T", seg="A", cable="C1", pair=1)}
    io_b = {"T": _sig("T", seg="A", cable="C1", pair=1),
            "X": _sig("X", seg="B", cable="C2", pair=1)}
    rows_a = [{"tag": "T", "cabinet": 0, "cioc": 0, "baseplate": 0, "slot": 0}]
    rows_b = [{"tag": "X", "cabinet": 0, "cioc": 0, "baseplate": 0, "slot": 1},
              {"tag": "T", "cabinet": 0, "cioc": 0, "baseplate": 0, "slot": 0}]
    rule_id, reason = attribute_forcing_rule("T", (0, 0, 0, 0), (0, 0, 0, 2),
                                             io_a, io_b, rows_a, rows_b, rules)
    assert rule_id == "RULE-01"
    assert "mix" in reason.lower()
