"""Excel/CSV reader with header-row detection (P1-1).

Reads xlsx/xlsm/xls/csv (multi-sheet), keeps every sheet as a raw string
grid, and finds the header row by scoring the first 30 rows against the
mapper's synonym dictionary. Merged header cells read back as blanks except
the top-left cell; a scoring follow-up row is joined into a two-row header.
Every data row keeps its original Excel row number for TQ provenance.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
import io as _io

from rapidfuzz import fuzz

HEADER_SCAN_ROWS = 30
HEADER_MIN_SCORE = 1.0  # at least one cell must match a known name


@dataclass
class RawSheet:
    name: str
    grid: List[List[str]]  # string grid, row 0 = Excel row 1
    n_excel_rows: int = 0


def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_table(path_or_bytes, filename: str) -> List[RawSheet]:
    """Read xlsx/xlsm/xls/csv into raw string grids, one per sheet."""
    import pandas as pd

    name = filename.lower()
    sheets: List[RawSheet] = []
    if name.endswith(".csv"):
        if isinstance(path_or_bytes, (str, Path)):
            df = pd.read_csv(path_or_bytes, header=None, dtype=str, keep_default_na=False,
                             encoding_errors="replace")
        else:
            df = pd.read_csv(path_or_bytes, header=None, dtype=str, keep_default_na=False,
                             encoding_errors="replace")
        grid = [[_cell_str(v) for v in row] for row in df.values.tolist()]
        sheets.append(RawSheet(name="sheet1", grid=grid, n_excel_rows=len(grid)))
        return sheets

    if isinstance(path_or_bytes, (str, Path)):
        xls = pd.ExcelFile(path_or_bytes)
    else:
        xls = pd.ExcelFile(_io.BytesIO(path_or_bytes.read()
                           if hasattr(path_or_bytes, "read") else path_or_bytes))
    for sheet_name in xls.sheet_names:
        df = xls.parse(sheet_name, header=None, dtype=str, keep_default_na=False)
        grid = [[_cell_str(v) for v in row] for row in df.values.tolist()]
        # Drop fully-empty trailing rows (pandas pads ragged sheets)
        while grid and not any(c for c in grid[-1]):
            grid.pop()
        if grid:
            sheets.append(RawSheet(name=str(sheet_name), grid=grid, n_excel_rows=len(grid)))
    return sheets


def _clean(cell: str) -> str:
    """Lowercase, separators (-> _, -, ., /) unified to spaces, collapsed."""
    import re as _re
    return _re.sub(r"\s+", " ", _re.sub(r"[_\-./]", " ", cell.strip().lower())).strip()


def _row_score(row: List[str], synonyms) -> Tuple[float, int]:
    """Sum over cells of best synonym match (>=80 counts 1, else 0); + hits."""
    score, hits = 0.0, 0
    for cell in row:
        if not cell:
            continue
        clean = _clean(cell)
        best = 0.0
        for canonical, syns in synonyms.items():
            best = max(best, fuzz.token_sort_ratio(clean, _clean(canonical)))
            for syn in syns:
                best = max(best, fuzz.token_sort_ratio(clean, _clean(syn)))
        if best >= 80:
            score += best / 100.0
            hits += 1
    return score, hits


def find_header_row(grid: List[List[str]], synonyms) -> Tuple[int, float, List[str]]:
    """Return (row_index, score, header_cells).

    Scores rows 0..29; picks the max. If the next row also scores (two-row /
    merged headers), joins both cell-wise. Raises ValueError if nothing
    matches (caller shows manual-mapping UI).
    """
    if not grid:
        raise ValueError("Empty sheet: no rows to scan for a header.")
    scored = []
    for i, row in enumerate(grid[:HEADER_SCAN_ROWS]):
        s, hits = _row_score(row, synonyms)
        scored.append((s, hits, i))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best_score, _, best_i = scored[0]
    if best_score < HEADER_MIN_SCORE:
        raise ValueError(
            "No header row detected in the first "
            f"{min(HEADER_SCAN_ROWS, len(grid))} rows: no cell matched a known "
            "column name. Map the columns manually."
        )
    header = list(grid[best_i])
    # Two-row header: join a scoring follow-up row (merged header cells).
    if best_i + 1 < len(grid):
        s2, hits2 = _row_score(grid[best_i + 1], synonyms)
        if s2 >= HEADER_MIN_SCORE and hits2 >= 1:
            width = max(len(header), len(grid[best_i + 1]))
            header += [""] * (width - len(header))
            nxt = list(grid[best_i + 1]) + [""] * (width - len(grid[best_i + 1]))
            header = [f"{a} {b}".strip() if a and b and a != b else (a or b)
                      for a, b in zip(header, nxt)]
            return best_i, best_score + s2, header
    return best_i, best_score, header


def data_rows(grid: List[List[str]], header_idx: int, two_row: bool = False) -> List[Tuple[int, List[str]]]:
    """(excel_row_no_1based, cells) for rows below the header; skips blanks."""
    start = header_idx + (2 if two_row else 1)
    out = []
    for i in range(start, len(grid)):
        if any(c for c in grid[i]):
            out.append((i + 1, grid[i]))
    return out
