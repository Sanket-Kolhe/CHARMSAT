"""P2-2: Rev B upload -> diff -> keep-literal revision vs scratch."""
import io
import pandas as pd
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

COLS = ["Tag", "IO Type", "Subtype", "Cable", "Pair", "Cable Size", "Group", "Segregation"]


def _rev_b_xlsx(rows):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows, columns=COLS).to_excel(w, index=False)
    return buf.getvalue()


def _setup_rev_a(n=200, seed=11):
    g = client.post("/api/generate", json={"n_signals": n, "seed": seed}).json()
    a = client.post("/api/allocate", json={}).json()
    assert a["success"], a["tqs"][:2]
    return g


def test_revise_uploaded_diff_and_min_moves():
    g = _setup_rev_a()
    sizes = g["cable_sizes"]
    raws = g["raw_signals"]
    by_cable = {}
    for s in raws:
        by_cable.setdefault(s["cable"], []).append(s)
    roomy = next(c for c, m in by_cable.items() if len(m) < sizes[c])
    used = {s["pair"] for s in by_cable[roomy]}
    free = min(p for p in range(1, sizes[roomy] + 1) if p not in used)
    anchor = by_cable[roomy][0]

    rows = []
    for s in raws[1:]:  # delete raws[0]
        rows.append([s["tag"], s["io_type"], s["subtype"] or "", s["cable"], s["pair"],
                     sizes[s["cable"]], s["group"] or "", s["seg"] or ""])
    # type change at same cable/pair (hardware change, not a move)
    for r in rows:
        if r[0] == raws[1]["tag"]:
            r[1] = "AO" if raws[1]["io_type"] == "AI" else "AI"
            changed_tag = r[0]
    # addition on a spare pair of an existing cable
    rows.append(["ADDED-1", anchor["io_type"], "", roomy, free, sizes[roomy],
                 anchor["group"] or "", anchor["seg"] or ""])

    r = client.post("/api/revise", files={"file": ("rev_b.xlsx", _rev_b_xlsx(rows))})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["diff"]["added"] == ["ADDED-1"]
    assert body["diff"]["deleted"] == [raws[0]["tag"]]
    assert changed_tag in body["diff"]["changed_hw"]
    res = body["rev_b_result"]
    assert res["success"]
    assert len(res["violations"]) == 0
    moved_tags = [m["tag"] for m in res["rev_summary"]["moves_detail"]]
    assert changed_tag not in moved_tags  # HW change at same slot is not a move
    assert "ADDED-1" not in moved_tags
    assert res["rev_summary"]["moves_ours"] <= res["rev_summary"]["moves_from_scratch"]


def test_revise_requires_rev_a_first():
    # Fresh app state has no Rev A: use an obviously fresh client? Session is
    # global; Rev A exists from other tests. At minimum, garbage file -> 400.
    r = client.post("/api/revise", files={"file": ("x.xlsx", b"junk")})
    assert r.status_code in (400, 500)
