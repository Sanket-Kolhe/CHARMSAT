"""Template writer (P2-3): results into a COPY of a template, values only.

- Never writes into the original: the template is copied first.
- Values only: styles, merges, validations, formulas, widths untouched.
- Refuses to overwrite a formula cell unless the map allows it
  (TemplateWriteError -> caller falls back to a plain workbook + TQ).
- If the workbook has images/charts/drawings, openpyxl would drop them on
  save, so the XML patch writer is used instead (zip surgery: only the
  sheet XML cell values change, every other part byte-identical).
- Extra sheets (TQ log, audit incl. output hash) are appended only if the
  map allows them.
"""
import copy as _copy
import hashlib
import io as _io
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

DRAWING_MARKERS = ("xl/drawings/", "xl/media/", "xl/charts/")


class TemplateWriteError(Exception):
    pass


def load_template_map(path_or_dict) -> dict:
    if isinstance(path_or_dict, dict):
        return path_or_dict
    with open(path_or_dict, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def allocation_hash(rows: List[dict]) -> str:
    """SHA-256 over canonical allocation rows (deterministic key order)."""
    import json as _json
    canon = [{k: r.get(k) for k in
              ("tag", "cable", "pair", "cabinet", "cioc", "baseplate", "slot",
               "charm", "tb", "io_type", "subtype", "group", "seg")} for r in rows]
    return hashlib.sha256(_json.dumps(canon, sort_keys=True).encode()).hexdigest()


def rows_from_allocations(allocations) -> List[dict]:
    """AllocatedSlot list -> 1-based template row dicts."""
    rows = []
    for a in allocations:
        d = a.model_dump() if hasattr(a, "model_dump") else dict(a)
        rows.append({
            "tag": d.get("tag") or "", "cable": d.get("cable", ""), "pair": d.get("pair", 0),
            "cabinet": (d.get("cabinet") or 0) + 1, "cioc": (d.get("cioc") or 0) + 1,
            "baseplate": (d.get("baseplate") or 0) + 1, "slot": (d.get("slot") or 0) + 1,
            "charm": d.get("charm", ""), "tb": d.get("terminal_block", ""),
            "cabinet_name": d.get("cabinet_name", ""), "cioc_name": d.get("cioc_name", ""),
            "baseplate_name": d.get("baseplate_name", ""),
            "io_type": d.get("io_type") or "", "subtype": d.get("subtype") or "",
            "group": d.get("group") or "", "seg": d.get("seg") or "",
        })
    return rows


def has_drawings(template_path: Path) -> bool:
    with zipfile.ZipFile(template_path) as z:
        return any(n.startswith(DRAWING_MARKERS) for n in z.namelist())


def snapshot_workbook(path: Path) -> dict:
    """Structural snapshot for the fidelity test (values excluded)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=False)
    snap = {"sheets": wb.sheetnames, "per_sheet": {}}
    for ws in wb.worksheets:
        merges = sorted(str(r) for r in ws.merged_cells.ranges)
        vals = sorted(str(v) for v in wb.defined_names.values())
        dv = sorted(f"{d.sqref}:{d.type}:{d.formula1}" for d in ws.data_validations.dataValidation)
        cf = sorted(str(r) for r in ws.conditional_formatting._cf_rules)
        widths = {c: ws.column_dimensions[c].width for c in ws.column_dimensions}
        formulas = {}
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    formulas[cell.coordinate] = cell.value
        header_styles = {}
        for cell in ws[1]:
            header_styles[cell.coordinate] = (str(cell.font), str(cell.fill), str(cell.alignment))
        snap["per_sheet"][ws.title] = {
            "merges": merges, "defined_names": vals, "validations": dv,
            "cond_formats": cf, "widths": widths, "formulas": formulas,
            "header_styles": header_styles,
            "max_row": ws.max_row, "max_col": ws.max_column,
        }
    return snap


def _col_letter(col) -> str:
    import openpyxl.utils as _u
    if isinstance(col, int):
        return _u.get_column_letter(col)
    return str(col).strip().upper()


def write_openpyxl(template_path: Path, out_path: Path, tmap: dict,
                   rows: List[dict], summary: Optional[dict] = None,
                   extras: Optional[Dict[str, List[List[Any]]]] = None) -> None:
    import openpyxl
    shutil.copy(template_path, out_path)
    wb = openpyxl.load_workbook(out_path, keep_vba=template_path.suffix == ".xlsm")
    if tmap.get("allocation_sheet") not in wb.sheetnames:
        raise TemplateWriteError(f"sheet '{tmap.get('allocation_sheet')}' not in template")
    ws = wb[tmap["allocation_sheet"]]
    first = int(tmap.get("first_data_row", 2))
    columns: Dict[str, Any] = tmap.get("columns", {})
    allowed = set(tmap.get("allow_formula_overwrite", []))
    for i, row in enumerate(rows):
        for field, col in columns.items():
            cell = ws[f"{_col_letter(col)}{first + i}"]
            if cell.data_type == "f" and cell.coordinate not in allowed:
                raise TemplateWriteError(
                    f"template map targets formula cell {cell.coordinate} "
                    f"(sheet {ws.title}); refusing to overwrite")
            cell.value = row.get(field, "")
    for cell_ref, value in (tmap.get("summary_cells", {}) or {}).items():
        sheet_name, _, ref = cell_ref.partition("!")
        target = wb[sheet_name] if sheet_name in wb.sheetnames else ws
        target[ref or cell_ref] = value() if callable(value) else value
    if summary:
        for cell_ref, value in summary.items():
            sheet_name, _, ref = cell_ref.partition("!")
            target = wb[sheet_name] if sheet_name in wb.sheetnames else ws
            target[ref or cell_ref] = value
    if extras and tmap.get("extra_sheets", True):
        for title, grid in extras.items():
            w = wb.create_sheet(title=title[:31])
            for r in grid:
                w.append(r)
    wb.save(out_path)


def write_xml_patch(template_path: Path, out_path: Path, tmap: dict,
                    rows: List[dict]) -> None:
    """Values-only writer that preserves drawings/images/charts byte-identical."""
    import xml.etree.ElementTree as _ET
    NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    _ET.register_namespace("", NS["m"])

    with zipfile.ZipFile(template_path) as zin:
        names = zin.namelist()
        parts = {n: zin.read(n) for n in names}

    # sheet name -> sheet xml file
    wb_xml = _ET.fromstring(parts["xl/workbook.xml"])
    sheet_file = {}
    for i, sh in enumerate(wb_xml.findall(".//m:sheets/m:sheet", NS)):
        rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = _ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
        target = next(r.get("Target") for r in rels
                      if r.get("Id") == rid and "worksheet" in r.get("Type", ""))
        target = target.lstrip("/")
        sheet_file[sh.get("name")] = target if target.startswith("xl/") else "xl/" + target
    key = tmap.get("allocation_sheet")
    if key not in sheet_file:
        raise TemplateWriteError(f"sheet '{key}' not in template")
    fname = sheet_file[key]

    root = _ET.fromstring(parts[fname])
    first = int(tmap.get("first_data_row", 2))
    columns: Dict[str, Any] = tmap.get("columns", {})
    col_idx = {}
    for field, col in columns.items():
        letter = _col_letter(col)
        col_idx[field] = sum((ord(ch) - 64) * (26 ** p) for p, ch in enumerate(reversed(letter)))

    def ref_to_rowcol(ref: str):
        letters = "".join(ch for ch in ref if ch.isalpha())
        digits = "".join(ch for ch in ref if ch.isdigit())
        c = sum((ord(ch) - 64) * (26 ** p) for p, ch in enumerate(reversed(letters)))
        return int(digits), c

    want: Dict[tuple, str] = {}
    for i, row in enumerate(rows):
        for field, c in col_idx.items():
            want[(first + i, c)] = "" if row.get(field) is None else str(row.get(field, ""))

    for cr in root.findall(".//m:c", NS):
        ref = cr.get("r", "")
        if not ref:
            continue
        r, c = ref_to_rowcol(ref)
        if (r, c) not in want:
            continue
        for child in list(cr):
            cr.remove(child)
        cr.set("t", "inlineStr")
        is_el = _ET.SubElement(cr, f"{{{NS['m']}}}is")
        t_el = _ET.SubElement(is_el, f"{{{NS['m']}}}t")
        t_el.text = want.pop((r, c))

    # rows beyond the template's dimension: append new row elements
    sheetdata = root.find("m:sheetData", NS)
    existing = {}
    for row_el in root.findall(".//m:row", NS):
        existing[int(row_el.get("r"))] = row_el
    for (r, c), val in sorted(want.items()):
        row_el = existing.get(r)
        if row_el is None:
            row_el = _ET.SubElement(sheetdata, f"{{{NS['m']}}}row", {"r": str(r)})
            existing[r] = row_el
        cr = _ET.SubElement(row_el, f"{{{NS['m']}}}c", {"r": f"{_col_idx_to_letter(c)}{r}", "t": "inlineStr"})
        is_el = _ET.SubElement(cr, f"{{{NS['m']}}}is")
        t_el = _ET.SubElement(is_el, f"{{{NS['m']}}}t")
        t_el.text = val

    parts[fname] = _ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, parts[n])


def _col_idx_to_letter(idx: int) -> str:
    s = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def write_plain_workbook(out_path: Path, rows: List[dict],
                         tqs: List, audit: List[List[Any]]) -> None:
    """Fallback when the template cannot be written (MD 10.4): a plain
    allocation workbook. The filename (CHARMSAT_PLAIN_...) signals the
    template-map mismatch; the run is still fully usable."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Allocation"
    if rows:
        ws.append(list(rows[0].keys()))
        for r in rows:
            ws.append([r.get(k, "") for k in rows[0].keys()])
    if tqs:
        wt = wb.create_sheet("TQ_LOG")
        wt.append(["id", "kind", "tags", "rows", "rules", "message"])
        for t in tqs:
            d = t.model_dump() if hasattr(t, "model_dump") else dict(t)
            wt.append([d.get("id"), d.get("kind"), ",".join(d.get("tags", d.get("items", []))),
                       ",".join(map(str, d.get("rows", []))), ",".join(d.get("rule_ids", [])),
                       d.get("message", "")])
    wa = wb.create_sheet("AUDIT")
    for r in audit:
        wa.append(r)
    wb.save(out_path)


def write_template(template_path: Path, out_path: Path, tmap: dict,
                   rows: List[dict], summary: Optional[dict] = None,
                   extras: Optional[Dict[str, List[List[Any]]]] = None) -> str:
    """Write rows into a copy of the template. Returns 'openpyxl'|'xml'."""
    if has_drawings(template_path):
        if extras or summary:
            raise TemplateWriteError("template has drawings: extra sheets/summary need the plain path")
        write_xml_patch(template_path, out_path, tmap, rows)
        return "xml"
    write_openpyxl(template_path, out_path, tmap, rows, summary, extras)
    return "openpyxl"
