"""Mapping profiles: remember a confirmed customer mapping and reuse it."""
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
    ]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, sheet_name="IO", index=False, header=False)
    return buf.getvalue()


def _upload():
    return client.post("/api/upload", files={"file": ("io.xlsx", _messy_xlsx())}).json()["upload_id"]


def test_confirm_saves_profile_and_reuse_is_reported():
    uid = _upload()
    overrides = {"TAG_NAME": "Tag", "CHANNEL_TYPE": "IO Type", "CABLE_TAG": "Cable",
                 "Pair_No": "Pair", "Unit_Area": "Group", "Safety_Seg": "Segregation"}
    r = client.post("/api/mapping/confirm",
                    json={"upload_id": uid, "sheet": "IO", "overrides": overrides,
                          "profile_name": "ACME_IO"}).json()
    assert r["profile_saved"] == "ACME_IO"
    assert r["signal_count"] == 2

    # same headers, no overrides -> the saved profile is applied automatically
    uid2 = _upload()
    r2 = client.post("/api/mapping/confirm",
                     json={"upload_id": uid2, "sheet": "IO"}).json()
    assert r2["profile_used"] == "ACME_IO"
    assert r2["signal_count"] == 2

    profiles = client.get("/api/mapping/profiles").json()["profiles"]
    assert any(p["name"] == "ACME_IO" and p["overrides"]["TAG_NAME"] == "Tag" for p in profiles)


def test_delete_profile():
    uid = _upload()
    overrides = {"TAG_NAME": "Tag", "CHANNEL_TYPE": "IO Type", "CABLE_TAG": "Cable",
                 "Pair_No": "Pair", "Unit_Area": "Group", "Safety_Seg": None}
    client.post("/api/mapping/confirm",
                json={"upload_id": uid, "sheet": "IO", "overrides": overrides,
                      "profile_name": "TO_DELETE"})
    assert client.delete("/api/mapping/profiles/TO_DELETE").json()["deleted"] is True
    names = [p["name"] for p in client.get("/api/mapping/profiles").json()["profiles"]]
    assert "TO_DELETE" not in names
