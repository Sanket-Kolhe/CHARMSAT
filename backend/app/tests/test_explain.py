"""W2: 'why is this signal here' explains by re-deriving the rules it satisfies."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _allocated():
    client.get("/api/demo-init")
    r = client.post("/api/allocate", json={"use_rev_a_as_hints": False}).json()
    assert r["success"], r["tqs"][:2]
    return r


def test_explain_placed_signal_is_grounded_in_its_own_solution():
    r = _allocated()
    placed = [a for a in r["allocations"] if a["tag"]]
    assert placed
    # sample across the whole allocation
    for a in placed[:: max(1, len(placed) // 25)]:
        e = client.get(f"/api/explain/{a['tag']}").json()
        assert e["found"] and e["placed"]
        assert e["cabinet"] == a["cabinet"] and e["slot"] == a["slot"]
        assert e["charm"] == a["charm"]
        assert e["pinned_by"], f"{a['tag']} should report the rules pinning it"
        # every reported check that is *applicable* must hold for a clean solve
        assert all(c["satisfied"] for c in e["checks"]), (a["tag"], e["checks"])
        assert e["why_here"]


def test_explain_unknown_tag_is_reported_not_faked():
    _allocated()
    e = client.get("/api/explain/NO-SUCH-TAG-9999").json()
    assert e["found"] is False
    assert "not in the input" in e["reason"]


def test_explain_without_allocation_errors():
    # a fresh client still shares module state; force the empty case explicitly
    from app.main import session_state
    saved = session_state.pop("alloc_a", None)
    try:
        assert client.get("/api/explain/ANY").status_code == 400
    finally:
        if saved is not None:
            session_state["alloc_a"] = saved
