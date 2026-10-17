"""P2-1: three-stage engine - optimality, bounds, revision minimal moves."""
from app.models.rules import RuleSetConfig
from app.models.domain import Signal
from app.engine.generator import SyntheticGenerator
from app.engine.solve.engine import solve_allocation, solve_revision
from app.engine.solve.bridge import to_core_signals


def _sig(tag, cable, pair, group="G", seg="", io="AI", sub=None):
    return Signal(tag=tag, io_type=io, subtype=sub, cable=cable, pair=pair,
                  group=group, seg=seg or None)


def test_small_case_known_optimum():
    """30 signals in 12+6+... blocks: fits one cabinet, LB proves it."""
    sigs = ([_sig(f"T{i}", "C12", i, seg="A") for i in range(1, 13)] +
            [_sig(f"U{i}", "C6", i, seg="A") for i in range(1, 7)] +
            [_sig(f"V{i}", "C2", i, seg="B") for i in range(1, 3)] +
            [_sig(f"W{i}", "C6B", i, group="H", seg="B") for i in range(1, 7)] +
            [_sig(f"X{i}", "C2B", i, group="H", seg="B") for i in range(1, 3)])
    res, _, raw = solve_allocation(sigs, {"C12": 12, "C6": 6, "C2": 2, "C6B": 6, "C2B": 2},
                                   RuleSetConfig())
    assert res.success
    assert res.cabinets_used == 1
    assert res.lower_bound_cabinets == 1
    assert res.solver_status == "OPTIMAL"
    assert res.tqs == []
    # Named without gaps, spare rule honoured as empty baseplates
    assert res.required_empty_bp == 4
    assert all(v >= 4 for v in res.empty_bp_per_cabinet.values())


def test_group_split_raises_tq_with_reasons():
    big = [_sig(f"B{i}", "CBIG", 1, group="GIANT") for i in range(3)]
    # one cable per signal would break contiguity; instead one 24-pair cable trio
    sigs = [_sig(f"S{i}", f"C{i}", 1, group="GIANT") for i in range(40)]
    res, _, _ = solve_allocation(sigs, {f"C{i}": 24 for i in range(40)}, RuleSetConfig())
    assert res.success
    cap_tqs = [t for t in res.tqs if t.id.startswith("TQ-CAP-")]
    assert len(cap_tqs) == 1
    assert "R5-SPARE" in cap_tqs[0].rule_ids or "R1-GROUP" in cap_tqs[0].rule_ids


def test_revision_spare_pair_additions_zero_moves():
    rules = RuleSetConfig()
    gen = SyntheticGenerator(seed=7)
    sig_a, ci = gen.generate_dataset(n_signals=300)
    sizes_a = {c["cable_id"]: c["size"] for c in ci}
    res_a, prev_a, raw_a = solve_allocation(sig_a, sizes_a, rules)
    assert res_a.success
    # Add one signal on a free pair of an existing cable: zero moves expected.
    cable, size = next((c, s) for c, s in sizes_a.items()
                       if sum(1 for x in sig_a if x.cable == c) < s)
    used = {x.pair for x in sig_a if x.cable == cable}
    free = min(p for p in range(1, size + 1) if p not in used)
    first = next(x for x in sig_a if x.cable == cable)
    sig_b = list(sig_a) + [Signal(tag="ADDED-1", io_type=first.io_type, cable=cable,
                                  pair=free, group=first.group, seg=first.seg)]
    sizes_b = dict(sizes_a)
    res_b, _, _ = solve_revision(sig_b, sizes_b, rules, prev_a, sig_a,
                                 raw_a["rows"], to_core_signals(sig_a))
    assert res_b.success
    assert res_b.rev_summary.added_count == 1
    assert res_b.rev_summary.moves_ours == 0
    assert len(res_b.violations) == 0


def test_revision_moves_bounded_by_scratch():
    rules = RuleSetConfig()
    gen = SyntheticGenerator(seed=42)
    sig_a, ci = gen.generate_dataset(n_signals=500)
    sizes_a = {c["cable_id"]: c["size"] for c in ci}
    res_a, prev_a, raw_a = solve_allocation(sig_a, sizes_a, rules)
    sig_b, meta = gen.generate_revision_b(sig_a, cable_sizes=sizes_a)
    res_b, _, _ = solve_revision(sig_b, meta["cable_sizes"], rules, prev_a, sig_a,
                                 raw_a["rows"], to_core_signals(sig_a))
    assert res_b.success
    rs = res_b.rev_summary
    assert rs.moves_ours <= rs.moves_from_scratch
    unchanged = rs.unchanged_count + rs.moves_ours
    assert rs.moves_ours <= 0.10 * max(1, unchanged)  # <=10% of unchanged
    assert len(res_b.violations) == 0
