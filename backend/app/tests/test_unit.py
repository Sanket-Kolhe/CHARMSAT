import hashlib
import json
import pytest
from hypothesis import given, settings, strategies as st

from app.models.rules import RuleSetConfig
from app.models.domain import Signal
from app.engine.generator import SyntheticGenerator
from app.engine.validator import DataValidator
from app.engine.mapper import ColumnAutoMapper
from app.engine.solve.engine import solve_allocation
from app.engine.solve.bridge import rules_to_ref
from app.engine.hardware import HW_TABLE
import checker.check as checker_pkg
from app.engine.io.template_writer import rows_from_allocations


def _io_rows(signals):
    return [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
             "cable": s.cable, "pair": s.pair, "group": s.group or "",
             "seg": s.seg or ""} for s in signals]


def _check_alloc(signals, allocations, sizes, rules):
    rows = rows_from_allocations(allocations)
    return checker_pkg.check(_io_rows(signals), rows, rules_to_ref(rules),
                             HW_TABLE, sizes)

def test_generator_structure():
    gen = SyntheticGenerator(seed=123)
    signals, cables_info = gen.generate_dataset(n_signals=200)
    assert len(signals) == 200
    assert len(cables_info) > 0
    # Every signal belongs to a cable
    cable_ids = {c["cable_id"] for c in cables_info}
    for s in signals:
        assert s.cable in cable_ids
        assert s.pair >= 1

def test_independent_checker_zero_violations_on_valid_allocation():
    gen = SyntheticGenerator(seed=42)
    signals, cables_info = gen.generate_dataset(n_signals=300)
    cable_sizes = {c["cable_id"]: c["size"] for c in cables_info}

    rules = RuleSetConfig()
    valid, _, _ = DataValidator().validate(signals, cable_sizes)
    result, _, _ = solve_allocation(valid, cable_sizes, rules)

    assert result.success is True
    assert len(result.violations) == 0

    # Verify directly with the independent checker package
    found = _check_alloc(valid, result.allocations, cable_sizes, rules)
    assert [v for v in found if v["status"] == "violation"] == []

def test_hand_planted_violation_caught():
    gen = SyntheticGenerator(seed=99)
    signals, cables_info = gen.generate_dataset(n_signals=400)
    cable_sizes = {c["cable_id"]: c["size"] for c in cables_info}

    rules = RuleSetConfig()
    valid, _, _ = DataValidator().validate(signals, cable_sizes)
    result, _, _ = solve_allocation(valid, cable_sizes, rules)
    assert result.success is True
    signals = valid

    # Workbook-level plants via the checker package (in-memory rows here).
    rows = rows_from_allocations(result.allocations)
    seg_of = {s.tag: (s.seg or "") for s in signals}
    # 1. Plant A/B leak: move a row's allocation into a CIOC of the other train.
    units = {}
    for r in rows:
        if r["tag"]:
            units.setdefault((r["cabinet"], r["cioc"]), set()).add(seg_of[r["tag"]])
    leaked = [dict(r) for r in rows]
    has_a = any("A" in v and "B" not in v for v in units.values())
    pure_b = next((k for k, v in units.items() if "B" in v and "A" not in v), None)
    if has_a and pure_b is not None:
        victim = next(r for r in leaked if r["tag"] and seg_of[r["tag"]] == "A")
        victim["cabinet"], victim["cioc"] = pure_b
    else:
        pure_a = next(k for k, v in units.items() if "A" in v and "B" not in v)
        victim = next(r for r in leaked if r["tag"] and seg_of[r["tag"]] == "B")
        victim["cabinet"], victim["cioc"] = pure_a
    found = checker_pkg.check(_io_rows(signals), leaked, rules_to_ref(rules),
                              HW_TABLE, cable_sizes)
    assert any(v["rule"] == rules.ab_segregation.id and v["status"] == "violation"
               for v in found)

    # 2. Plant split cable: shift one pair off contiguity.
    split = [dict(r) for r in rows]
    by_cable = {}
    for r in split:
        by_cable.setdefault(r["cable"], []).append(r)
    cid = next(c for c, m in by_cable.items() if len(m) > 2)
    by_cable[cid][1]["slot"] = (by_cable[cid][1]["slot"] % 12) + 1
    found2 = checker_pkg.check(_io_rows(signals), split, rules_to_ref(rules),
                               HW_TABLE, cable_sizes)
    assert any(v["rule"] == "CABLE" and v["status"] == "violation" for v in found2)

def test_determinism_same_seed_gives_identical_output():
    """Same seed + same rules => identical allocation hash in TWO SEPARATE
    processes (P1-5). An in-process comparison cannot catch multi-worker or
    wall-clock non-determinism."""
    import subprocess
    import sys
    prog = (
        "import sys, json, hashlib; sys.path.insert(0, 'backend');"
        "from app.models.rules import RuleSetConfig;"
        "from app.engine.generator import SyntheticGenerator;"
        "from app.engine.solve.engine import solve_allocation;"
        "gen = SyntheticGenerator(seed=555);"
        "sig, c_info = gen.generate_dataset(n_signals=300);"
        "c_sizes = {c['cable_id']: c['size'] for c in c_info};"
        "res, _, _ = solve_allocation(sig, c_sizes, RuleSetConfig());"
        "print(hashlib.sha256(json.dumps([a.model_dump() for a in res.allocations], sort_keys=True).encode()).hexdigest())"
    )
    hashes = []
    for _ in range(2):
        out = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, check=True)
        hashes.append(out.stdout.strip())

    assert hashes[0] == hashes[1], "Allocations must be strictly deterministic given the same seed and input"

def test_data_validator_tq_generation():
    validator = DataValidator(spare_pct=10.0)
    bad_signals = [
        Signal(tag="TAG-1", io_type="", cable="CBL-1", pair=1), # blank type
        Signal(tag="TAG-2", io_type="AI", cable="CBL-1", pair=1),
        Signal(tag="TAG-2", io_type="AI", cable="CBL-1", pair=2), # duplicate tag
        Signal(tag="TAG-3", io_type="DI", cable="CBL-2", pair=99), # pair overflow
    ]
    cable_sizes = {"CBL-1": 12, "CBL-2": 6}
    valid, tqs, ledger = validator.validate(bad_signals, cable_sizes)

    assert len(tqs) >= 3
    tq_ids = {t.id for t in tqs}
    assert "TQ-DAT-01" in tq_ids  # blank type
    assert "TQ-DUP-TAG-2" in tq_ids  # duplicate tag
    assert "TQ-PAIR-CBL-2" in tq_ids  # pair overflow
    # Ledger covers every input row
    assert set(ledger) == {"TAG-1", "TAG-2", "TAG-3"}
    assert ledger["TAG-2"].startswith("held:")

def test_fuzzy_column_mapper():
    mapper = ColumnAutoMapper()
    fuzzed_headers = ["TAG_NAME", "CHANNEL_TYPE", "CABLE_TAG", "Pair_No", "Unit_Area", "Safety_Seg", "Junk_Col"]
    res = mapper.map_columns(fuzzed_headers)

    mapped_dict = {m.detected_column: m.mapped_canonical for m in res.matches}
    assert mapped_dict.get("TAG_NAME") == "Tag"
    assert mapped_dict.get("CHANNEL_TYPE") == "IO Type"
    assert mapped_dict.get("CABLE_TAG") == "Cable"
    assert mapped_dict.get("Pair_No") == "Pair"
    assert mapped_dict.get("Unit_Area") == "Group"
    assert mapped_dict.get("Safety_Seg") == "Segregation"
    assert "Junk_Col" in res.unmapped_columns

# Hypothesis property test
@settings(max_examples=3, deadline=20000)
@given(st.integers(min_value=100, max_value=400), st.integers(min_value=1, max_value=1000))
def test_hypothesis_zero_violations_property(n_signals, seed):
    gen = SyntheticGenerator(seed=seed)
    signals, cables_info = gen.generate_dataset(n_signals=n_signals)
    cable_sizes = {c["cable_id"]: c["size"] for c in cables_info}

    rules = RuleSetConfig()
    valid, _, _ = DataValidator().validate(signals, cable_sizes)
    result, _, _ = solve_allocation(valid, cable_sizes, rules)

    assert result.success is True
    found = _check_alloc(valid, result.allocations, cable_sizes, rules)
    assert [v for v in found if v["status"] == "violation"] == [], \
        f"Hypothesis property failed on seed {seed}"
