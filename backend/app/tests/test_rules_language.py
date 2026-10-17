"""P3 rule-language tests: schema validation + generic rules that flow all the
way to the solver and the independent checker with no code change."""
import yaml
import pytest

from app.models.rules import RuleSetConfig, GenericRuleConfig
from app.engine.rules.loader import (
    RuleSchemaError, validate_yaml, validate_document, rule_schema, compile_document)
from app.engine.generator import SyntheticGenerator
from app.engine.validator import DataValidator
from app.engine.solve.engine import solve_allocation
from app.engine.solve.bridge import rules_to_ref
from app.engine.io.template_writer import rows_from_allocations
import checker.check as chk


def _dataset(n=300, seed=11):
    gen = SyntheticGenerator(seed=seed)
    sig, ci = gen.generate_dataset(n_signals=n)
    sizes = {c["cable_id"]: c["size"] for c in ci}
    return sig, sizes


def _solve_and_check(rules, n=300, seed=11):
    """Run the full path and return (result, violations_from_independent_checker)."""
    sig, sizes = _dataset(n, seed)
    validator = DataValidator()
    valid, _, ledger = validator.validate(sig, sizes)
    res, _, _ = solve_allocation(valid, sizes, rules)
    held = {t for t, v in ledger.items() if v.startswith("held:")}
    held |= {t for q in res.tqs for t in (q.items or ())}
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "", "seg": s.seg or ""}
               for s in valid]
    ref = rules_to_ref(rules)
    found = chk.check(io_rows, rows_from_allocations(res.allocations), ref,
                      ref.get("hardware_table"), sizes, frozenset(held))
    return res, [v for v in found if v["status"] == "violation"]


def test_schema_is_valid_json_schema():
    s = rule_schema()
    assert s["type"] == "object"
    assert "custom_rules" in s["properties"]


def test_schema_rejects_unknown_key_and_bad_enum():
    assert not validate_yaml("spare_capacity:\n  spare_percantage: 10\n")[0]  # typo
    ok, errors = validate_yaml("custom_rules:\n  - id: X\n    relation: nope\n"
                               "    attribute: seg\n    level: cioc\n")
    assert not ok and any("relation" in e for e in errors)


def test_partial_document_uses_defaults_and_round_trips():
    rs = RuleSetConfig.from_yaml("spare_capacity:\n  spare_percentage: 20\n")
    assert rs.spare_capacity.spare_percentage == 20
    assert rs.ab_segregation.level == "cioc"  # untouched default
    # to_yaml -> from_yaml is schema-clean and stable
    assert RuleSetConfig.from_yaml(rs.to_yaml()).model_dump() == rs.model_dump()


def test_new_rule_of_existing_kind_needs_no_code():
    """Adding a never-share rule is pure data: it compiles into segregation."""
    rs = RuleSetConfig()
    rs.custom_rules = [GenericRuleConfig(id="R-IO", name="No IO mix", relation="different",
                                         attribute="seg", level="cabinet")]
    ref = rules_to_ref(rs)
    assert [r["id"] for r in ref["segregation"]] == ["RULE-01", "R-IO"]
    assert ref["segregation"][1]["level"] == "cabinet"


def test_at_most_k_group_per_cabinet_solves_clean():
    rs = RuleSetConfig()
    rs.custom_rules = [GenericRuleConfig(id="R-CAP", name="max 3 groups", relation="at_most_k",
                                         attribute="group", level="cabinet", k_value=3)]
    res, viol = _solve_and_check(rs, n=400)
    assert res.success and not viol
    # the cap must actually be honoured in the output
    by_cab = {}
    for a in res.allocations:
        if a.tag:
            by_cab.setdefault(a.cabinet, set()).add(a.group)
    assert all(len(g) <= 3 for g in by_cab.values())


def test_cohesion_group_per_cabinet_solves_clean():
    rs = RuleSetConfig()
    rs.custom_rules = [GenericRuleConfig(id="R-COH", name="groups together", relation="same",
                                         attribute="group", level="cabinet")]
    res, viol = _solve_and_check(rs, n=300)
    assert res.success and not viol


def test_all_distinct_never_share_holds_mixed_cables_with_tq():
    """ALL_DISTINCT never-share on a per-cable attribute holds mixed cables
    with a TQ instead of producing an illegal layout (coverage preserved)."""
    rs = RuleSetConfig()
    rs.custom_rules = [GenericRuleConfig(id="R-TYPE", name="no mixed IO", relation="different",
                                         attribute="io_type", level="cioc")]
    sig, sizes = _dataset(200)
    validator = DataValidator()
    valid, _, _ = validator.validate(sig, sizes)
    res, _, _ = solve_allocation(valid, sizes, rs)
    conflict_tqs = [q for q in res.tqs if q.id.startswith("TQ-CONFLICT") or q.id.startswith("TQ-COH")]
    assert conflict_tqs, "mixed-IO cables should raise conflict TQs"
    placed = {a.tag for a in res.allocations if a.tag}
    held = {t for q in res.tqs for t in (q.items or ())}
    assert placed | held == {s.tag for s in valid}  # placed + held = all


def test_hardware_table_is_data_driven():
    doc = {
        "hardware_table": [
            {"io_type": "AI", "subtype": "*", "charm": "CUSTOM AI", "tb": "Custom TB"},
        ]
    }
    rs = RuleSetConfig.model_validate(doc)
    from app.engine.hardware import hardware_for
    table = [h.model_dump() for h in rs.hardware_table]
    assert hardware_for("AI", None, table) == ("CUSTOM AI", "Custom TB")


def test_determinism_same_rules_same_rows():
    rs = RuleSetConfig()
    rs.custom_rules = [GenericRuleConfig(id="R-CAP", name="cap", relation="at_most_k",
                                         attribute="group", level="cabinet", k_value=4)]
    sig, sizes = _dataset(250)
    r1, _, raw1 = solve_allocation(sig, sizes, rs)
    r2, _, raw2 = solve_allocation(sig, sizes, rs)
    assert rows_from_allocations(r1.allocations) == rows_from_allocations(r2.allocations)


def test_compile_document_exposes_compiled_rules():
    doc = """
custom_rules:
  - id: R-NEVER
    relation: different
    attribute: subtype
    level: baseplate
"""
    compiled = compile_document(doc)
    assert compiled["segregation"][-1]["id"] == "R-NEVER"
