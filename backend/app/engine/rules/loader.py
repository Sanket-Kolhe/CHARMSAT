"""Rule-set loader (P3): YAML -> schema-validated -> RuleSetConfig -> compiled.

Nothing here is rule-specific: the schema (schema.json) defines the language
and the compiler (solve/bridge.rules_to_ref) turns every rule into the plain
dicts the solver and the independent checker consume. Adding a rule of an
existing kind is a YAML edit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"


class RuleSchemaError(ValueError):
    """Raised when a rule document does not satisfy schema.json."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("Rule set failed schema validation:\n  - " + "\n  - ".join(errors))


def rule_schema() -> Dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_document(doc: Any) -> List[str]:
    """Return a list of human-readable schema errors ([] = valid)."""
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(rule_schema())
    errors = []
    for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in e.path) or "(root)"
        errors.append(f"{loc}: {e.message}")
    return errors


def _parse_yaml(yaml_str: str) -> Any:
    try:
        doc = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise RuleSchemaError([f"YAML parse error: {e}"]) from e
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        raise RuleSchemaError(["(root): rule document must be a mapping"])
    return doc


def validate_yaml(yaml_str: str) -> Tuple[bool, List[str]]:
    """(ok, errors) for a YAML rule document (never raises for bad input)."""
    try:
        doc = _parse_yaml(yaml_str)
    except RuleSchemaError as e:
        return False, e.errors
    errors = validate_document(doc)
    return (not errors), errors


def load_rule_set(yaml_str: str) -> "RuleSetConfig":
    """Schema-validate then build the model. Raises RuleSchemaError with all
    problems at once so a customer fixes one file, not one error per try."""
    from app.models.rules import RuleSetConfig

    doc = _parse_yaml(yaml_str)
    errors = validate_document(doc)
    if errors:
        raise RuleSchemaError(errors)
    try:
        return RuleSetConfig.model_validate(doc)
    except Exception as e:  # pydantic cross-field issues the schema cannot express
        raise RuleSchemaError([f"model: {e}"]) from e


def compile_document(yaml_str: str) -> Dict[str, Any]:
    """Compile a rule document to the plain ref-rules dict (diagnostics/demo)."""
    from app.engine.solve.bridge import rules_to_ref

    return rules_to_ref(load_rule_set(yaml_str))
