"""P1-1: header-row detection on messy real-world-style files."""
import io
import pandas as pd

from app.engine.io.reader import read_table, find_header_row, data_rows
from app.engine.mapper import SYNONYM_DICTIONARY


def _messy_grid():
    """Title rows + renamed/shuffled headers + junk column, as raw grid."""
    header = ["CABLE_TAG", "TAG_NAME", "Junk_Col", "CHANNEL_TYPE", "Pair_No",
              "Unit_Area", "Safety_Seg", "Cable_Pairs"]
    rows = [
        ["ACME PROJECT - IO SCHEDULE", "", "", "", "", "", "", ""],
        ["Rev B - do not use Rev A", "", "", "", "", "", "", ""],
        header,
        ["CBL-1", "TT-1001", "x", "AI", 1, "GRP-01", "A", 12],
        ["CBL-1", "TT-1002", "x", "AI", 2, "GRP-01", "A", 12],
        ["CBL-2", "XV-2001", "x", "DO", 1, "GRP-01", "", 6],
    ]
    return rows


def _to_xlsx_bytes(sheets: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(w, sheet_name=name, index=False, header=False)
    return buf.getvalue()


def test_reader_finds_header_below_title_rows():
    raw = _to_xlsx_bytes({"IO": _messy_grid()})
    sheets = read_table(raw, "messy.xlsx")
    assert len(sheets) == 1
    idx, score, header = find_header_row(sheets[0].grid, SYNONYM_DICTIONARY)
    assert idx == 2
    assert "TAG_NAME" in header and "CHANNEL_TYPE" in header
    rows = data_rows(sheets[0].grid, idx)
    assert len(rows) == 3
    assert rows[0][0] == 4  # Excel row number provenance (1-based)


def test_reader_two_sheets():
    raw = _to_xlsx_bytes({"IO-A": _messy_grid(), "IO-B": _messy_grid()})
    sheets = read_table(raw, "two.xlsx")
    assert [s.name for s in sheets] == ["IO-A", "IO-B"]
    for sh in sheets:
        idx, _, _ = find_header_row(sh.grid, SYNONYM_DICTIONARY)
        assert idx == 2


def test_reader_csv_with_bom():
    text = "\ufeffTAG_NAME,CHANNEL_TYPE,CABLE_TAG,Pair_No\nTT-1,AI,CBL-1,1\nTT-2,DI,CBL-1,2\n"
    sheets = read_table(io.BytesIO(text.encode("utf-8")), "list.csv")
    assert len(sheets) == 1
    idx, _, header = find_header_row(sheets[0].grid, SYNONYM_DICTIONARY)
    assert idx == 0
    assert any("TAG_NAME" in h for h in header)


def test_reader_two_row_header_joined():
    rows = [
        ["TAG", "IO TYPE", "CABLE", "PAIR"],
        ["Tag Number", "", "", ""],
        ["TT-1", "AI", "CBL-1", 1],
    ]
    raw = _to_xlsx_bytes({"IO": rows})
    sheets = read_table(raw, "two-row.xlsx")
    idx, _, header = find_header_row(sheets[0].grid, SYNONYM_DICTIONARY)
    assert idx == 0
    assert header[0] == "TAG Tag Number"
    rows_out = data_rows(sheets[0].grid, idx)
    assert len(rows_out) == 2  # sub-header row is consumed, not data


def test_reader_no_header_raises_helpful_error():
    import pytest
    rows = [["hello", "world"], ["foo", "bar"]]
    raw = _to_xlsx_bytes({"IO": rows})
    sheets = read_table(raw, "junk.xlsx")
    with pytest.raises(ValueError, match="No header row detected"):
        find_header_row(sheets[0].grid, SYNONYM_DICTIONARY)
