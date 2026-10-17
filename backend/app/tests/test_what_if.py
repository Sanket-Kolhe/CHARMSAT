"""W1: what-if scoring recomputes in isolation and never commits."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _allocated():
    client.get("/api/demo-init")
    r = client.post("/api/allocate", json={"use_rev_a_as_hints": False}).json()
    assert r["success"]
    return r


def test_add_signal_is_placed_and_reported_without_committing():
    base = _allocated()
    before = client.post("/api/allocate", json={"use_rev_a_as_hints": False}).json()
    w = client.post("/api/what-if", json={
        "kind": "add_signal",
        "signals_extra": [{"tag": "WI-TEST-1", "io_type": "AI", "subtype": "",
                           "cable": "WI-NEW-CABLE", "pair": 1,
                           "group": "WI-GROUP", "seg": "A"}],
    }).json()
    assert w["committed"] is False
    assert w["hypothetical"]["coverage_pct"] == 100.0
    assert any(loc["tag"] == "WI-TEST-1" for loc in w["added_locations"])
    # the committed plan is untouched
    after = client.post("/api/allocate", json={"use_rev_a_as_hints": False}).json()
    assert after["cabinets_used"] == before["cabinets_used"]
    assert len(after["allocations"]) == len(before["allocations"])
    assert not any(a.get("tag") == "WI-TEST-1" for a in after["allocations"])


def test_spare_margin_what_if_reports_impact():
    _allocated()
    w = client.post("/api/what-if", json={"kind": "spare_change", "spare_percentage": 0}).json()
    assert w["hypothetical"]["coverage_pct"] == 100.0
    assert w["delta"]["cabinets"] is not None


def test_what_if_rejects_invalid_rule_document():
    _allocated()
    r = client.post("/api/what-if", json={"kind": "rule_change",
                                          "rules": {"custom_rules": [{"id": "B", "relation": "bogus",
                                                                       "attribute": "group",
                                                                       "level": "cabinet"}]}})
    assert r.status_code == 400
