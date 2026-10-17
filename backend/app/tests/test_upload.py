"""P1-1/P1-2: real upload -> mapping proposal -> confirm -> session signals."""
import io
import pandas as pd
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _messy_xlsx() -> bytes:
    rows = [
        ["ACME PROJECT - IO SCHEDULE", "", "", "", "", ""],
        ["TAG_NAME", "CHANNEL_TYPE", "CABLE_TAG", "Pair_No", "Unit_Area", "Safety_Seg"],
        ["TT-1001", "AI", "CBL-1", 1, "GRP-01", "A"],
        ["TT-1002", "AI", "CBL-1", 2, "GRP-01", "A"],
        ["XV-2001", "DO", "CBL-2", 1, "GRP-01", ""],
    ]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, sheet_name="IO", index=False, header=False)
    return buf.getvalue()


def test_upload_proposes_mapping():
    r = client.post("/api/upload", files={"file": ("io.xlsx", _messy_xlsx())})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "io.xlsx"
    assert len(body["sheets"]) == 1
    sh = body["sheets"][0]
    assert sh["header_row"] == 1
    assert sh["n_rows"] == 3
    got = {m["detected_column"]: m["mapped_canonical"] for m in sh["mapping"]["matches"]}
    assert got["TAG_NAME"] == "Tag"
    assert got["CHANNEL_TYPE"] == "IO Type"
    assert got["CABLE_TAG"] == "Cable"
    assert sh["mapping"]["missing_required"] == []
    assert len(sh["preview_rows"]) == 3


def test_confirm_mapping_applies_overrides_to_data():
    up = client.post("/api/upload", files={"file": ("io.xlsx", _messy_xlsx())}).json()
    uid = up["upload_id"]
    # Engineer swaps nothing here, but ignores Safety_Seg via override.
    overrides = {"TAG_NAME": "Tag", "CHANNEL_TYPE": "IO Type", "CABLE_TAG": "Cable",
                 "Pair_No": "Pair", "Unit_Area": "Group", "Safety_Seg": None}
    r = client.post("/api/mapping/confirm",
                    json={"upload_id": uid, "sheet": "IO", "overrides": overrides})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["signal_count"] == 3
    assert body["cable_count"] == 2
    sigs = body["raw_signals"]
    assert [s["tag"] for s in sigs] == ["TT-1001", "TT-1002", "XV-2001"]
    assert [s["row_no"] for s in sigs] == [3, 4, 5]  # Excel provenance
    assert all(s["seg"] is None for s in sigs)        # override ignored the column
    assert sigs[0]["group"] == "GRP-01"


def test_upload_rejects_empty_and_garbage():
    r = client.post("/api/upload", files={"file": ("empty.xlsx", b"")})
    assert r.status_code == 400
    r = client.post("/api/upload", files={"file": ("x.xlsx", b"not an excel file")})
    assert r.status_code == 400


def test_confirm_unknown_upload_id_404():
    r = client.post("/api/mapping/confirm", json={"upload_id": "nope"})
    assert r.status_code == 404
