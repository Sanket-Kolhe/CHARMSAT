"""W3: the offline rule assistant drafts schema-valid rules from a sentence.

It only drafts wording. It never receives IO rows and never places signals.
The optional LLM drafter (hosted API) is env-gated, schema-checked and tagged
by provenance; the deterministic parser is always the first pass and fallback.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.engine import llm_drafter
from app.engine.rule_assistant import RuleAssistant, CONFIDENCE_THRESHOLD

client = TestClient(app)


def test_draft_is_deterministic_and_schema_valid():
    a = client.post("/api/rules/parse-nl", json={"text": "Segregate Train A and B at CIOC level"}).json()
    b = client.post("/api/rules/parse-nl", json={"text": "Segregate Train A and B at CIOC level"}).json()
    assert a["draft"]["id"] == b["draft"]["id"], "same sentence must yield the same rule id"
    assert a["draft"]["relation"] == "different"
    assert a["draft"]["attribute"] == "seg"
    assert a["draft"]["level"] == "cioc"
    assert a["schema_ok"] is True and a["schema_errors"] == []
    assert a["requires_human_confirmation"] is True
    assert "never places signals" in a["assistant_banner"]


def test_k_sentence_extracts_capacity():
    r = client.post("/api/rules/parse-nl",
                    json={"text": "at most 3 groups per cabinet"}).json()
    assert r["draft"]["relation"] == "at_most_k"
    assert r["draft"]["k_value"] == 3
    assert r["schema_ok"] is True


def test_confirmed_draft_applies_and_solves_cleanly():
    client.get("/api/demo-init")
    original_yaml = client.get("/api/rules").json()["yaml"]
    try:
        draft = client.post("/api/rules/parse-nl",
                            json={"text": "keep each group on one cabinet"}).json()["draft"]
        rules = client.get("/api/rules").json()["rules"]
        rules["custom_rules"] = rules.get("custom_rules", []) + [draft]
        upd = client.post("/api/rules", json={"rules": rules})
        assert upd.status_code == 200, upd.text
        res = client.post("/api/allocate", json={"use_rev_a_as_hints": False}).json()
        assert res["success"] and res["coverage_pct"] == 100.0
    finally:
        client.post("/api/rules", json={"yaml": original_yaml})



def test_offline_parser_stays_offline_even_if_llm_enabled(monkeypatch):
    monkeypatch.setenv("CHARMSAT_LLM_ENABLED", "1")
    monkeypatch.setenv("CHARMSAT_LLM_API_KEY", "test-key")
    called = {"n": 0}

    def _boom(text):  # must never be reached when allow_llm=False
        called["n"] += 1
        return {"relation": "different", "attribute": "seg", "level": "cioc"}

    monkeypatch.setattr(llm_drafter, "draft_rule_via_llm", _boom)
    res = RuleAssistant.draft_rule("Segregate Train A and B at CIOC level", allow_llm=False)
    assert called["n"] == 0
    assert res.source == "parser"
    assert res.confidence >= CONFIDENCE_THRESHOLD


def test_ambiguous_sentence_scores_below_threshold():
    res = RuleAssistant.draft_rule(
        "don't let the safety loops sit with non-safety, and cap each cabinet at four groups",
        allow_llm=False)
    assert res.confidence < CONFIDENCE_THRESHOLD


def test_llm_used_only_when_configured_and_opted_in(monkeypatch):
    monkeypatch.setenv("CHARMSAT_LLM_ENABLED", "1")
    monkeypatch.setenv("CHARMSAT_LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_drafter, "llm_enabled", lambda: True)
    monkeypatch.setattr(llm_drafter, "draft_rule_via_llm", lambda text: {
        "relation": "at_most_k", "attribute": "group", "level": "cabinet",
        "k_value": 4, "classes": None,
    })
    res = RuleAssistant.draft_rule("arbitrary vague sentence with no clear cues at all here", allow_llm=True)
    assert res.source == "llm"
    assert res.draft.relation == "at_most_k" and res.draft.k_value == 4


def test_invalid_llm_draft_falls_back_to_parser(monkeypatch):
    monkeypatch.setenv("CHARMSAT_LLM_ENABLED", "1")
    monkeypatch.setenv("CHARMSAT_LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_drafter, "llm_enabled", lambda: True)
    # schema-valid keys but an illegal enum value -> must be rejected
    monkeypatch.setattr(llm_drafter, "draft_rule_via_llm", lambda text: {
        "relation": "bogus", "attribute": "group", "level": "cabinet",
    })
    res = RuleAssistant.draft_rule("some vague phrasing with nothing to latch on to", allow_llm=True)
    assert res.source == "parser"
    assert "schema" in res.message.lower() or "offline parser" in res.message.lower()


def test_llm_disabled_without_key(monkeypatch):
    monkeypatch.setenv("CHARMSAT_LLM_ENABLED", "1")
    monkeypatch.delenv("CHARMSAT_LLM_API_KEY", raising=False)
    assert llm_drafter.llm_enabled() is False


def test_endpoint_reports_provenance_and_llm_availability(monkeypatch):
    monkeypatch.delenv("CHARMSAT_LLM_API_KEY", raising=False)
    r = client.post("/api/rules/parse-nl",
                    json={"text": "Segregate Train A and B at CIOC level", "allow_llm": True}).json()
    assert r["source"] == "parser"
    assert r["llm_available"] is False
    assert "confidence" in r
