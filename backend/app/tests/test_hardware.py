"""P1-4: hardware table per Emerson PDS (data, not code)."""
import pytest

from app.engine.hardware import hardware_for, normalise_subtype
from app.models.rules import RuleSetConfig
from app.models.domain import Signal
from app.engine.solve.engine import solve_allocation
from app.engine.solve.bridge import rules_to_ref
import checker.check as checker_pkg
from app.engine.io.template_writer import rows_from_allocations


def test_do_high_current_isolated_fused():
    charm, tb = hardware_for("DO", "HIGH_CURRENT")
    assert charm == "DO 24V DC Isolated"
    assert tb == "Fused Injected Power"


def test_do_high_current_synonyms():
    for raw in ["high current", "hi current", "HIGH_CURRENT", "horn", "beacon", "ISOLATED"]:
        charm, tb = hardware_for("DO", raw)
        assert (charm, tb) == ("DO 24V DC Isolated", "Fused Injected Power"), raw


def test_do_relay_high_side_relay_tb():
    charm, tb = hardware_for("DO", "relay")
    assert charm == "DO 24V DC High-Side"
    assert tb == "Relay Output"


def test_do_normal_high_side_standard():
    for raw in [None, "", "SOV", "sov"]:
        charm, tb = hardware_for("DO", raw)
        assert (charm, tb) == ("DO 24V DC High-Side", "Standard"), raw


def test_ai_ao_di_standard():
    assert hardware_for("AI", "") == ("AI 4-20 mA HART", "Standard")
    assert hardware_for("AO", "") == ("AO 4-20 mA HART", "Standard")
    assert hardware_for("DI", "")[1] == "Standard"


def test_unknown_subtype_needs_tq():
    assert hardware_for("DO", "QUANTUM_FLUX") == (None, None)
    assert hardware_for("ZZ", "") == (None, None)
    assert normalise_subtype("QUANTUM_FLUX") is None


def test_solver_and_checker_agree_on_do_hardware():
    rules = RuleSetConfig()
    signals = [
        Signal(tag="SOV-1", io_type="DO", subtype="HIGH_CURRENT", cable="C1", pair=1, group="G"),
        Signal(tag="SOV-2", io_type="DO", subtype="HIGH_CURRENT", cable="C1", pair=2, group="G"),
        Signal(tag="RY-1", io_type="DO", subtype="RELAY", cable="C2", pair=1, group="G"),
        Signal(tag="RY-2", io_type="DO", subtype="RELAY", cable="C2", pair=2, group="G"),
        Signal(tag="XV-1", io_type="DO", subtype="SOV", cable="C2", pair=3, group="G"),
        Signal(tag="XV-2", io_type="DO", subtype="SOV", cable="C2", pair=4, group="G"),
    ]
    res, _, _ = solve_allocation(signals, {"C1": 2, "C2": 6}, rules)
    assert res.success
    by_tag = {a.tag: a for a in res.allocations if a.tag}
    assert (by_tag["SOV-1"].charm, by_tag["SOV-1"].terminal_block) == ("DO 24V DC Isolated", "Fused Injected Power")
    assert (by_tag["RY-1"].charm, by_tag["RY-1"].terminal_block) == ("DO 24V DC High-Side", "Relay Output")
    assert (by_tag["XV-1"].charm, by_tag["XV-1"].terminal_block) == ("DO 24V DC High-Side", "Standard")
    from app.engine.hardware import HW_TABLE
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "",
                "seg": s.seg or ""} for s in signals]
    found = checker_pkg.check(io_rows, rows_from_allocations(res.allocations),
                              rules_to_ref(rules), HW_TABLE, {"C1": 2, "C2": 6})
    assert [v for v in found if v["status"] == "violation"] == []
