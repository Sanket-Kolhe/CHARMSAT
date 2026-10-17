"""Rule language package (P3).

The whole rule set is data: a YAML document validated by schema.json
(JSON Schema, Draft 2020-12) before it becomes a RuleSetConfig. Adding a new
rule of an existing kind is a YAML edit, never a code change.
"""
from app.engine.rules.loader import (  # noqa: F401
    RuleSchemaError, validate_document, validate_yaml, load_rule_set,
    compile_document,
)
