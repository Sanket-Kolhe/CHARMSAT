"""P2-4: checker independence (AST) + planted violations on the workbook."""
import ast
from pathlib import Path

import pytest

from checker.check import check, read_workbook_rows, plant_violation
from app.models.rules import RuleSetConfig
from app.engine.generator import SyntheticGenerator
from app.engine.validator import DataValidator
from app.engine.solve.engine import solve_allocation
from app.engine.solve.bridge import rules_to_ref, to_core_signals
from app.engine.hardware import HW_TABLE
from app.engine.io.template_writer import (
    load_template_map, write_template, rows_from_allocations)


def test_checker_imports_nothing_from_app():
    root = Path("backend/checker")
    assert root.exists()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            else:
                continue
            for m in mods:
                assert not m.startswith("app") and m != "backend", \
                    f"{path}: forbidden import {m}"


@pytest.fixture(scope="module")
def clean_case(tmp_path_factory):
    """Correct workbook + checker inputs, built by running code."""
    rules = RuleSetConfig()
    gen = SyntheticGenerator(seed=42)
    sig, ci = gen.generate_dataset(n_signals=300)
    sizes = {c["cable_id"]: c["size"] for c in ci}
    # Same as the real pipeline: validate (normalises types) then solve.
    valid, _, _ = DataValidator().validate(sig, sizes)
    res, _, _ = solve_allocation(valid, sizes, rules)
    assert res.success
    tmap = load_template_map(Path("data/templates/synthetic_map.yaml"))
    out = tmp_path_factory.mktemp("wb") / "clean.xlsx"
    write_template(Path("data/templates/synthetic_template.xlsx"), out, tmap,
                   rows_from_allocations(res.allocations))
    wb_bytes = out.read_bytes()
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "",
                "seg": s.seg or ""} for s in valid]
    ctx = {"wb": wb_bytes, "tmap": tmap, "io": io_rows,
           "rules": rules_to_ref(rules), "hw": HW_TABLE, "sizes": sizes}
    return ctx


def _check(ctx, wb_bytes):
    rows = read_workbook_rows(wb_bytes, ctx["tmap"])
    return check(ctx["io"], rows, ctx["rules"], ctx["hw"], ctx["sizes"]), rows


def test_clean_workbook_zero_violations(clean_case):
    viols, rows = _check(clean_case, clean_case["wb"])
    real = [v for v in viols if v["status"] == "violation"]
    assert real == [], real[:3]
    assert len(rows) > 300  # signals + spare positions


PLANTS = {
    "ab_leak": "RULE-01",      # R2-AB never-share (repo id)
    "split_cable": "CABLE",
    "wrong_tb": "R6-HW",
    "straddle": "CABLE",
    "spare_breach": "R5-SPARE",
    "missing_signal": "COVERAGE",
    "duplicate": "COVERAGE",
}


@pytest.mark.parametrize("plant_type,rule", list(PLANTS.items()))
def test_planted_violation_caught(clean_case, plant_type, rule):
    tampered = plant_violation(clean_case["wb"], clean_case["tmap"], plant_type)
    viols, _ = _check(clean_case, tampered)
    real = [v for v in viols if v["status"] == "violation"]
    assert real, f"{plant_type}: nothing caught"
    assert any(v["rule"] == rule for v in real), \
        f"{plant_type}: rule {rule} not among {[v['rule'] for v in real][:5]}"
