"""End-to-end demo check (STEP 2): upload -> allocate -> export -> check.

Runs the real HTTP routes via TestClient on a messy unseen-style file
(fixed seed), then a revision. Exits 0 only if the whole demo path works:
  coverage 100%, 0 checker violations, export downloads, plant caught,
  Rev B moves_ours <= moves_from_scratch.
Usage: make demo-check
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.engine.generator import SyntheticGenerator  # noqa: E402

SEED = 2026
N = 500
HEADER = ["TAG NO.", "Signal Type", "Multicore", "PAIR", "Unit_Area", "Train", "Cable_Pairs"]

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{PASS if cond else FAIL}] {name} {detail}")


def messy_bytes():
    gen = SyntheticGenerator(seed=SEED)
    sig, ci = gen.generate_dataset(n_signals=N)
    sizes = {c["cable_id"]: c["size"] for c in ci}
    df = gen.to_dataframe(sig, ci)
    rename = {"Tag": "TAG NO.", "IO Type": "Signal Type", "Cable": "Multicore",
              "Pair": "PAIR", "Group": "Unit_Area", "Segregation": "Train",
              "Cable Size": "Cable_Pairs"}
    df = df.rename(columns=rename)
    df["Junk"] = "x"
    df = df[["Multicore", "TAG NO.", "Junk", "Signal Type", "PAIR", "Unit_Area", "Train", "Cable_Pairs"]]
    grid = [["MESSY CUSTOMER IO LIST - Rev A", "", "", "", "", "", "", ""],
            ["exported from legacy system - headers shuffled", "", "", "", "", "", "", ""]]
    grid += [list(df.columns)] + df.values.tolist()
    # Two known defects: duplicate tag + A/B on one cable (both must become TQs).
    grid[4][1] = grid[3][1]
    # A/B mix on a DIFFERENT cable (held dup rows are excluded from later
    # checks, so same-cable defects would mask each other).
    first_cable = grid[5][0]
    hit_b = False
    for r in grid[5:]:
        if r[0] == first_cable:
            r[6] = "A" if not hit_b else "B"
            hit_b = True
            if r[6] == "B":
                break
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(grid).to_excel(w, sheet_name="IO List", index=False, header=False)
        pd.DataFrame(grid).to_excel(w, sheet_name="Spare Sheet", index=False, header=False)
    return buf.getvalue(), sig, sizes


def main():
    c = TestClient(app)
    raw, _, _ = messy_bytes()

    up = c.post("/api/upload", files={"file": ("unseen_messy.xlsx", raw)})
    check("upload parses messy file", up.status_code == 200, up.text[:120] if up.status_code != 200 else "")
    if up.status_code != 200:
        return 1
    body = up.json()
    sh = next(s for s in body["sheets"] if s["name"] == "IO List")
    got = {m["detected_column"]: m["mapped_canonical"] for m in sh["mapping"]["matches"]}
    check("header row + mapping found", sh["header_row"] == 2 and not sh["mapping"]["missing_required"], str(got))
    overrides = {m["detected_column"]: m["mapped_canonical"] for m in sh["mapping"]["matches"]}
    cf = c.post("/api/mapping/confirm",
                json={"upload_id": body["upload_id"], "sheet": "IO List", "overrides": overrides})
    check("mapping confirm loads signals", cf.status_code == 200 and cf.json()["signal_count"] == N)

    a = c.post("/api/allocate", json={}).json()
    check("allocate succeeds", a["success"], f"{a['cabinets_used']} cabs / LB {a['lower_bound_cabinets']} / {a['solver_status']}")
    check("coverage 100%", a["coverage_pct"] == 100.0, str(a["coverage_pct"]))
    check("0 checker violations", len(a["violations"]) == 0, str(a["violations"][:1]))
    check("TQs explain held rows", len(a["tqs"]) >= 1, f"{len(a['tqs'])} TQs")

    e = c.post("/api/export/excel")
    check("export downloads", e.status_code == 200 and len(e.content) > 10000, f"{len(e.content)} bytes")

    ch = c.post("/api/check").json()
    check("checker clean on export", ch["n_violation"] == 0, f"hash {ch['output_hash'][:12]}")

    p = c.post("/api/checker/plant-violation", json={"plant_type": "ab_leak"}).json()
    check("planted violation caught", p["violations_detected_by_independent_checker"] > 0)

    # Rev B: drop 2%, change one type, add on a spare pair.
    cf_body = cf.json()
    raws = cf_body["raw_signals"]
    sizes = cf_body["cable_sizes"]
    by_cable = {}
    for s in raws:
        by_cable.setdefault(s["cable"], []).append(s)
    drop = {s["tag"] for s in raws[: max(1, N // 50)]}
    roomy = next(c for c, m in by_cable.items() if len(m) < sizes.get(c, 0))
    free = min(p for p in range(1, sizes[roomy] + 1) if p not in {s["pair"] for s in by_cable[roomy]})
    anchor = by_cable[roomy][0]
    rows = []
    changed = None
    for s in raws:
        if s["tag"] in drop:
            continue
        t = s["io_type"]
        if changed is None and s["tag"] not in drop:
            t = "AO" if s["io_type"] == "AI" else "AI"
            changed = s["tag"]
        rows.append([s["tag"], t, s["subtype"] or "", s["cable"], s["pair"],
                     sizes.get(s["cable"], ""), s["group"] or "", s["seg"] or ""])
    rows.append(["ADDED-9", anchor["io_type"], "", roomy, free, sizes[roomy],
                 anchor["group"] or "", anchor["seg"] or ""])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows, columns=["Tag", "IO Type", "Subtype", "Cable", "Pair",
                                    "Cable Size", "Group", "Segregation"]).to_excel(w, index=False)
    r = c.post("/api/revise", files={"file": ("rev_b.xlsx", buf.getvalue())})
    check("revise succeeds", r.status_code == 200, r.text[:150] if r.status_code != 200 else "")
    if r.status_code == 200:
        rb = r.json()["rev_b_result"]
        rs = rb["rev_summary"]
        check("revB ours <= scratch", rs["moves_ours"] <= rs["moves_from_scratch"],
              f"{rs['moves_ours']} vs {rs['moves_from_scratch']}")
        check("revB 0 violations", len(rb["violations"]) == 0)

    bad = [n for n, ok, _ in results if not ok]
    print(f"\ndemo-check: {len(results) - len(bad)}/{len(results)} passed")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
