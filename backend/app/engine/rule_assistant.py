import hashlib
import re
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
from app.models.rules import GenericRuleConfig

# Below this deterministic confidence we consider the sentence ambiguous and,
# only if the operator opted in, hand it to the optional LLM drafter.
CONFIDENCE_THRESHOLD = 0.6

# Allowed values are the closed vocabulary of the rule language (P3). Both the
# deterministic parser and the LLM drafter must land inside this set; the JSON
# Schema is the final backstop.
ALLOWED = {
    "relation": ["same", "different", "at_most_k"],
    "attribute": ["group", "seg", "io_type", "subtype"],
    "level": ["cabinet", "cioc", "baseplate"],
}


@dataclass
class DraftResult:
    draft: Optional[GenericRuleConfig]
    message: str
    source: str          # "parser" | "llm"
    confidence: float    # 0..1 (deterministic parser's self-assessment)


class RuleAssistant:
    """
    Natural-Language Rule Assistant.

    Two-stage, provenance-tagged:
      1. A deterministic keyword/regex parser (always runs, fully offline).
      2. If the parser is unsure AND the operator enabled the optional LLM
         drafter, a hosted model drafts a candidate. The candidate must pass
         the same JSON Schema (see rules.loader) or it is discarded.

    Either way a human confirms the draft before it is applied, and no IO-list
    rows ever leave the process. The assistant NEVER places signals.
    """

    @staticmethod
    def _cues(text_lower: str) -> Tuple[set, set, set]:
        attr = set()
        if any(w in text_lower for w in ["seg", "train", "segment", "safety", "sis", "trip", "area a/b"]):
            attr.add("seg")
        if any(w in text_lower for w in ["subtype", "sub-type", "sov", "solenoid", "beacon", "horn",
                                         "isolated", "relay"]):
            attr.add("subtype")
        if any(w in text_lower for w in ["io type", "i/o", "signal type", "analog", "digital"]) \
                or re.search(r"\b(ai|ao|di|do)\b", text_lower):
            attr.add("io_type")
        if any(w in text_lower for w in ["group", "unit", "loop", "process", "system"]):
            attr.add("group")

        level = set()
        if "baseplate" in text_lower or "base plate" in text_lower or re.search(r"\bbp\b", text_lower):
            level.add("baseplate")
        if "cioc" in text_lower or "card" in text_lower or "controller" in text_lower:
            level.add("cioc")
        if "cabinet" in text_lower or "cab" in text_lower or "rack" in text_lower:
            level.add("cabinet")

        relation = set()
        if any(w in text_lower for w in ["different", "separate", "segregate", "segregation", "never share",
                                         "apart", "not share", "must not share", "isolate"]):
            relation.add("different")
        if any(w in text_lower for w in ["at most", "no more than", "maximum", "limit", "cap ", "capped", "up to"]):
            relation.add("at_most_k")
        if any(w in text_lower for w in ["same", "together", "co-locate", "colocate", "on one", "one cabinet",
                                         "single", "keep"]):
            relation.add("same")
        return attr, level, relation

    @staticmethod
    def _parse(text: str) -> DraftResult:
        text_lower = text.lower().strip()
        attr_hits, level_hits, rel_hits = RuleAssistant._cues(text_lower)

        # priority order mirrors the original first-match parser; group is the default
        attr = next((a for a in ["seg", "subtype", "io_type", "group"] if a in attr_hits), "group")
        # priority: more specific levels first when several were named
        level = "baseplate" if "baseplate" in level_hits else ("cioc" if "cioc" in level_hits else "cabinet")

        relation = "same"
        k_val = 1
        if "different" in rel_hits:
            relation = "different"
        elif "at_most_k" in rel_hits:
            relation = "at_most_k"
            m = re.search(r"(\d+)", text_lower)
            k_val = int(m.group(1)) if m else 2

        classes: Optional[List[str]] = None
        if relation == "different" and attr == "seg":
            if re.search(r"\b(a\b.*\bb|train a.*train b|a/b|a and b)\b", text_lower):
                classes = ["A", "B"]

        # self-assessment: unique cue hits raise confidence, ambiguity lowers it
        conf = 0.0
        if rel_hits:
            conf += 0.4 / len(rel_hits)
        if attr_hits:
            conf += 0.3 / len(attr_hits)
        if level_hits:
            conf += 0.3 / len(level_hits)
        if len(rel_hits) > 1:
            conf -= 0.35          # "same ... and cap ..." is compound/ambiguous
        if len(attr_hits) > 1:
            conf -= 0.30
        if (" and " in text_lower) or ("," in text_lower):
            conf -= 0.10
        if len(text_lower.split()) > 20:
            conf -= 0.15
        conf = max(0.0, min(1.0, round(conf, 2)))

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rule_id = f"RULE-GEN-{int(digest[:8], 16) % 900 + 100}"
        name = f"Assistant: {attr.capitalize()} {relation.replace('_', ' ').capitalize()} per {level.capitalize()}"
        draft = GenericRuleConfig(
            id=rule_id, name=name, enabled=True, relation=relation, attribute=attr,
            level=level, k_value=k_val, classes=classes,
            description=f"Draft compiled from: '{text}'. Configured as: {relation} {attr} per {level} (k={k_val}).",
        )
        msg = (f"Compiled English intent into a structured rule: "
               f"relation '{relation}', attribute '{attr}', level '{level}'"
               + (f", k={k_val}" if relation == "at_most_k" else "")
               + (f", classes={classes}" if classes else "") + ".")
        return DraftResult(draft=draft, message=msg, source="parser", confidence=conf)

    @staticmethod
    def parse_natural_language_rule(text: str) -> Tuple[Optional[GenericRuleConfig], str]:
        """Backwards-compatible deterministic parse (never calls the network)."""
        res = RuleAssistant._parse(text)
        return res.draft, res.message

    @staticmethod
    def draft_rule(text: str, allow_llm: bool = False) -> DraftResult:
        """Hybrid entry point. Deterministic first; optional LLM only when unsure.

        The LLM candidate is schema-validated (as custom rule) before it is
        returned; if it fails, we keep the deterministic draft. Provenance is
        reported in `source` so a non-reproducible step is never hidden.
        """
        parsed = RuleAssistant._parse(text)
        if not allow_llm or parsed.confidence >= CONFIDENCE_THRESHOLD:
            return parsed

        from app.engine import llm_drafter
        from app.engine.rules.loader import validate_document
        if not llm_drafter.llm_enabled():
            parsed.message += " (LLM drafter not configured; used the offline parser.)"
            return parsed

        candidate: Optional[Dict[str, Any]] = llm_drafter.draft_rule_via_llm(text)
        if not candidate:
            parsed.message += " (LLM drafter returned nothing usable; used the offline parser.)"
            return parsed
        # force provenance/schema-safe fields, then validate the whole document
        candidate.setdefault("id", parsed.draft.id)
        candidate.setdefault("name", parsed.draft.name)
        candidate.setdefault("enabled", True)
        candidate.setdefault("description", f"LLM draft from: '{text}'.")
        errors = validate_document({"custom_rules": [candidate]})
        if errors:
            parsed.message += f" (LLM draft failed schema: {errors[0]}; used the offline parser.)"
            return parsed
        try:
            draft = GenericRuleConfig.model_validate(candidate)
        except Exception:
            parsed.message += " (LLM draft was not a valid rule; used the offline parser.)"
            return parsed
        return DraftResult(draft=draft, message="Drafted by the optional LLM assistant and schema-checked.",
                           source="llm", confidence=parsed.confidence)
