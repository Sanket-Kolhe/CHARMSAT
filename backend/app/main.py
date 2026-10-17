import time
import uuid
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd

from app.models.domain import Signal, Cable, AllocatedSlot, AllocResult, Violation, TQ, RevisionSummary
from app.models.rules import RuleSetConfig, GenericRuleConfig
from app.engine.generator import SyntheticGenerator
from app.engine.mapper import ColumnAutoMapper, ColumnMappingResult
from app.engine.validator import DataValidator
from app.engine.solve.engine import solve_allocation, solve_revision
from app.engine.solve.bridge import to_core_signals
from app.engine.baselines import BaselineEngine
from app.engine.naming import NameGenerator
from app.engine.excel_io import ExcelIO
from app.engine.storage import StorageEngine
from app.engine.rule_assistant import RuleAssistant
from app.engine.io.reader import read_table, find_header_row, data_rows
from app.engine.mapper import propose_mapping as propose_sheet_mapping, apply_mapping
from app.engine.mapper import SYNONYM_DICTIONARY

from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(
    title="CHARMSAT Engine API",
    description="Rule-driven DeltaV IO Signal Sudoku allocation engine with CP-SAT and independent verification",
    version="1.0.0"
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = StorageEngine()
current_rules = RuleSetConfig()

# In-memory session state for demo
session_state: Dict[str, Any] = {
    "signals_a": [],
    "cables_info_a": [],
    "alloc_a": None,
    "signals_b": [],
    "alloc_b": None,
}

class GenerateRequest(BaseModel):
    n_signals: int = 1000
    seed: int = 42
    fuzz_headers: bool = False
    inject_defects: bool = False
    defect_types: Optional[List[str]] = None

class MapColumnsRequest(BaseModel):
    columns: List[str]

class ParseNLRuleRequest(BaseModel):
    text: str
    allow_llm: bool = False  # operator opt-in; no effect unless the LLM drafter is configured

class AllocateRequest(BaseModel):
    signals: Optional[List[Signal]] = None
    cable_sizes: Optional[Dict[str, int]] = None
    rules: Optional[RuleSetConfig] = None
    use_rev_a_as_hints: bool = False

def _moves_between(prev_allocs, new_allocs) -> int:
    """Measured moves: tags present in both allocations whose slot changed."""
    def pos(a):
        return (a.cabinet, a.cioc, a.baseplate, a.slot)
    prev = {a.tag: pos(a) for a in prev_allocs if a.tag}
    new = {a.tag: pos(a) for a in new_allocs if a.tag}
    return sum(1 for t, p in prev.items() if t in new and new[t] != p)


def _hw_table_for(rules: RuleSetConfig):
    """Hardware table as data from the rule set (P3); None = in-code default."""
    return [h.model_dump() for h in rules.hardware_table] if rules.hardware_table else None


# Reference-checker rule labels -> repo rule ids (display translation only).
_RULE_ID_MAP = {"CABLE": "RULE-02", "R1-GROUP": "RULE-03", "R5-SPARE": "RULE-04",
                "R6-HW": "RULE-06", "COVERAGE": "RULE-00", "CAPACITY": "RULE-04"}


def _verify_on_export(allocations, signals, cable_sizes, rules, held_tags, waived_groups):
    """Write allocations into a template copy, read the FILE back with the
    independent checker (backend/checker, no app imports). Returns
    (violations, waived_count, export_bytes, output_hash)."""
    import tempfile as _tf
    from pathlib import Path as _Path
    import checker.check as _chk
    from app.engine.solve.bridge import rules_to_ref
    from app.engine.io.template_writer import (
        load_template_map, write_template, rows_from_allocations, allocation_hash)

    template = _Path("data/templates/synthetic_template.xlsx")
    tmap = load_template_map(_Path("data/templates/synthetic_map.yaml"))
    rows = rows_from_allocations(allocations)
    ohash = allocation_hash(rows)
    with _tf.TemporaryDirectory() as tmp:
        out = _Path(tmp) / "verify.xlsx"
        write_template(template, out, tmap, rows)
        data = out.read_bytes()
    back = _chk.read_workbook_rows(data, {"allocation_sheet": tmap["allocation_sheet"],
                                          "first_data_row": tmap["first_data_row"],
                                          "columns": tmap["columns"]})
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "",
                "seg": s.seg or ""} for s in signals]
    found = _chk.check(io_rows, back, rules_to_ref(rules), _hw_table_for(rules), cable_sizes,
                       frozenset(held_tags), frozenset(waived_groups))
    from app.models.domain import Violation
    violations = [Violation(rule_id=_RULE_ID_MAP.get(v["rule"], v["rule"]),
                            rule_name=_RULE_ID_MAP.get(v["rule"], v["rule"]),
                            message=v["message"], status=v["status"])
                  for v in found if v["status"] == "violation"]
    waived = sum(1 for v in found if v["status"] != "violation")
    return violations, waived, data, ohash

class PlantViolationRequest(BaseModel):
    plant_type: str = "ab_leak"  # 'ab_leak' | 'split_cable' | 'cross_boundary' | 'scatter_group'

class BenchmarkRequest(BaseModel):
    signal_count: int = 1000
    seed: int = 42

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "CHARMSAT", "engine": "OR-Tools CP-SAT", "independent_checker": "active"}

@app.get("/api/rules")
def get_rules():
    return {
        "rules": current_rules.model_dump(),
        "yaml": current_rules.to_yaml()
    }

@app.get("/api/rules/schema")
def rules_schema():
    """The JSON Schema that every rule document is validated against (P3)."""
    from app.engine.rules.loader import rule_schema
    return rule_schema()

@app.post("/api/rules/validate")
def validate_rules(payload: Dict[str, Any]):
    """Validate a rule document (YAML string or dict) without applying it."""
    from app.engine.rules.loader import validate_yaml, validate_document, RuleSchemaError
    if "yaml" in payload and payload["yaml"]:
        ok, errors = validate_yaml(payload["yaml"])
        return {"ok": ok, "errors": errors}
    if "rules" in payload:
        errors = validate_document(payload["rules"])
        return {"ok": not errors, "errors": errors}
    return {"ok": False, "errors": ["provide 'yaml' or 'rules'"]}

@app.post("/api/rules")
def update_rules(payload: Dict[str, Any]):
    global current_rules
    from app.engine.rules.loader import RuleSchemaError
    try:
        if "yaml" in payload and payload["yaml"]:
            current_rules = RuleSetConfig.from_yaml(payload["yaml"])
        elif "rules" in payload:
            from app.engine.rules.loader import validate_document
            errors = validate_document(payload["rules"])
            if errors:
                raise RuleSchemaError(errors)
            current_rules = RuleSetConfig.model_validate(payload["rules"])
        else:
            raise HTTPException(status_code=400, detail="provide 'yaml' or 'rules'")
    except RuleSchemaError as e:
        raise HTTPException(status_code=400, detail={"schema_errors": e.errors})
    storage.save_rule_set("active", current_rules.to_yaml())
    return {
        "rules": current_rules.model_dump(),
        "yaml": current_rules.to_yaml()
    }

@app.post("/api/rules/parse-nl")
def parse_nl_rule(req: ParseNLRuleRequest):
    from app.engine import llm_drafter
    llm_available = llm_drafter.llm_enabled()
    # The operator opts into the LLM drafter per request; the deterministic parser
    # is always the first pass and the fallback, so the offline path never breaks.
    res = RuleAssistant.draft_rule(req.text, allow_llm=bool(req.allow_llm) and llm_available)
    draft = res.draft
    # W3: every draft is schema-validated before it is offered for human confirmation.
    errors: List[str] = []
    if draft is not None:
        from app.engine.rules.loader import validate_document
        errors = validate_document({"custom_rules": [draft.model_dump()]})
    return {
        "draft": draft.model_dump() if draft else None,
        "message": res.message,
        "source": res.source,
        "confidence": res.confidence,
        "llm_available": llm_available,
        "schema_ok": draft is not None and not errors,
        "schema_errors": errors,
        "requires_human_confirmation": True,
        "assistant_banner": "Rule Assistant is active for wording syntax only. AI never places signals.",
    }

@app.post("/api/generate")
def generate_dataset(req: GenerateRequest):
    gen = SyntheticGenerator(seed=req.seed)
    signals, cables_info = gen.generate_dataset(
        n_signals=req.n_signals,
        inject_defects=req.inject_defects,
        defect_types=req.defect_types
    )
    df = gen.to_dataframe(signals, cables_info, fuzz_headers=req.fuzz_headers)

    # Save to session
    session_state["signals_a"] = signals
    session_state["cables_info_a"] = cables_info

    return {
        "signal_count": len(signals),
        "cable_count": len(cables_info),
        "columns": list(df.columns),
        "sample_rows": df.head(15).to_dict(orient="records"),
        "raw_signals": [s.__dict__ for s in signals[:200]],  # first 200 for preview
        "cable_sizes": {c["cable_id"]: c["size"] for c in cables_info}
    }

@app.post("/api/map-columns")
def map_columns(req: MapColumnsRequest):
    mapper = ColumnAutoMapper()
    result = mapper.map_columns(req.columns)
    out = result.model_dump()
    # Mapping profiles: if this header signature was confirmed before, surface it.
    sig = storage.header_signature(req.columns)
    profile = storage.find_mapping_profile_by_signature(sig)
    out["profile_match"] = profile
    return out


class ConfirmMappingRequest(BaseModel):
    upload_id: str
    sheet: Optional[str] = None
    header_row: Optional[int] = None  # 0-based grid index; auto-detected if omitted
    overrides: Optional[Dict[str, Optional[str]]] = None  # detected header -> canonical (None = ignore)
    profile_name: Optional[str] = None  # save this mapping under a customer name


@app.get("/api/mapping/profiles")
def list_mapping_profiles():
    return {"profiles": storage.list_mapping_profiles()}


@app.delete("/api/mapping/profiles/{name}")
def delete_mapping_profile(name: str):
    return {"deleted": storage.delete_mapping_profile(name)}


def _parse_upload_to_signals(raw: bytes, filename: str, overrides=None, sheet=None):
    """Shared upload parsing: sheets + header + mapping + signals + sizes."""
    sheets = read_table(raw, filename or "upload.xlsx")
    if not sheets:
        raise HTTPException(status_code=400, detail="No readable sheets in file")
    sh = next((s for s in sheets if s.name == (sheet or sheets[0].name)), sheets[0])
    h_idx, _, header = find_header_row(sh.grid, SYNONYM_DICTIONARY)
    if overrides:
        mapping = {h: overrides.get(h) for h in header}
    else:
        cols = [[row[i] if i < len(row) else "" for _, row in data_rows(sh.grid, h_idx)]
                for i in range(len(header))]
        proposal = propose_sheet_mapping(header, cols)
        if proposal.missing_required:
            raise HTTPException(
                status_code=400,
                detail={"missing_required": proposal.missing_required,
                        "matches": proposal.model_dump()["matches"],
                        "hint": "Confirm column overrides and re-post."})
        mapping = {m.detected_column: m.mapped_canonical for m in proposal.matches}
    return sh, h_idx, header, mapping, apply_mapping(sh.grid, h_idx, mapping)


@app.post("/api/upload")
async def upload_io_list(file: UploadFile = File(...)):
    """Real IO-list upload (P1-1): xlsx/xlsm/xls/csv, multi-sheet.

    Finds the header row per sheet and proposes a column mapping with
    evidence. Nothing is allocated yet; confirm via /api/mapping/confirm.
    The raw file is stored under data/uploads/{upload_id}/ (gitignored).
    """
    from pathlib import Path as _Path
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    try:
        sheets = read_table(raw, file.filename or "upload.xlsx")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")
    if not sheets:
        raise HTTPException(status_code=400, detail="No readable sheets in file")

    upload_id = uuid.uuid4().hex[:12]
    updir = _Path("data/uploads") / upload_id
    updir.mkdir(parents=True, exist_ok=True)
    (updir / (file.filename or "upload.xlsx")).write_bytes(raw)

    session_state.setdefault("uploads", {})[upload_id] = {
        "filename": file.filename, "sheets": sheets,
    }

    out_sheets = []
    for sh in sheets:
        try:
            h_idx, h_score, header = find_header_row(sh.grid, SYNONYM_DICTIONARY)
        except ValueError as e:
            out_sheets.append({"name": sh.name, "n_rows": len(sh.grid),
                               "error": str(e), "mapping": None})
            continue
        cols = [[row[i] if i < len(row) else "" for _, row in data_rows(sh.grid, h_idx)]
                for i in range(len(header))]
        proposal = propose_sheet_mapping(header, cols)
        preview = [dict(zip(header, (row + [""] * len(header))[:len(header)]))
                   for _, row in data_rows(sh.grid, h_idx)[:15]]
        out_sheets.append({
            "name": sh.name, "n_rows": len(data_rows(sh.grid, h_idx)),
            "header_row": h_idx, "header_score": round(h_score, 2),
            "header_cells": header,
            "mapping": proposal.model_dump(), "preview_rows": preview,
        })
    return {"upload_id": upload_id, "filename": file.filename, "sheets": out_sheets}


@app.post("/api/mapping/confirm")
def confirm_mapping(req: ConfirmMappingRequest):
    """Apply the confirmed mapping to the uploaded data (P1-2).

    Overrides come from the mapping screen dropdowns. Stores real Signals +
    cable sizes in the session, exactly like the demo-data path.
    """
    uploads = session_state.get("uploads", {})
    up = uploads.get(req.upload_id)
    if not up:
        raise HTTPException(status_code=404, detail="Unknown upload_id; upload the file again")
    sheet = next((s for s in up["sheets"] if s.name == (req.sheet or up["sheets"][0].name)),
                 up["sheets"][0])
    h_idx = req.header_row if req.header_row is not None else find_header_row(
        sheet.grid, SYNONYM_DICTIONARY)[0]
    header = sheet.grid[h_idx]
    sig = storage.header_signature(header)
    saved_profile = None if req.overrides else storage.find_mapping_profile_by_signature(sig)
    if req.overrides:
        mapping = {h: req.overrides.get(h) for h in header}
    elif saved_profile:
        mapping = {h: saved_profile["overrides"].get(h) for h in header}
    else:
        cols = [[row[i] if i < len(row) else "" for _, row in data_rows(sheet.grid, h_idx)]
                for i in range(len(header))]
        proposal = propose_sheet_mapping(header, cols)
        mapping = {m.detected_column: m.mapped_canonical for m in proposal.matches}
    signals, cable_sizes = apply_mapping(sheet.grid, h_idx, mapping)
    if req.profile_name and req.overrides:
        storage.save_mapping_profile(req.profile_name, req.overrides, sig)

    session_state["signals_a"] = signals
    session_state["cables_info_a"] = [{"cable_id": c, "size": s} for c, s in cable_sizes.items()]
    session_state["upload_mapping"] = {"upload_id": req.upload_id, "sheet": sheet.name,
                                       "header_row": h_idx, "mapping": mapping,
                                       "profile_used": saved_profile["name"] if saved_profile else None}
    return {
        "signal_count": len(signals),
        "cable_count": len({s.cable for s in signals if s.cable}),
        "columns": header,
        "profile_used": saved_profile["name"] if saved_profile else None,
        "profile_saved": req.profile_name if (req.profile_name and req.overrides) else None,
        "sample_rows": [dict(zip(header, [s.tag, s.io_type, s.subtype or "", s.cable,
                                          s.pair, cable_sizes.get(s.cable, ""),
                                          s.group or "", s.seg or ""])) for s in signals[:15]],
        "raw_signals": [dict(tag=s.tag, io_type=s.io_type, subtype=s.subtype, cable=s.cable,
                             pair=s.pair, group=s.group, seg=s.seg,
                             row_no=s.row_no, extra=s.extra) for s in signals],
        "cable_sizes": cable_sizes,
    }

@app.post("/api/allocate")
def run_allocation(req: AllocateRequest):
    global current_rules
    rules_to_use = req.rules or current_rules

    # Use session signals if none provided
    signals = req.signals
    if not signals and session_state.get("signals_a"):
        signals = session_state["signals_a"]
    elif signals:
        # Convert Pydantic/dict to Signal dataclass if needed
        signals = [Signal(**s) if isinstance(s, dict) else s for s in signals]

    if not signals:
        raise HTTPException(status_code=400, detail="No signals provided for allocation")

    cable_sizes = req.cable_sizes or {}
    if not cable_sizes and session_state.get("cables_info_a"):
        cable_sizes = {c["cable_id"]: c["size"] for c in session_state["cables_info_a"]}

    # Step 1: Validate data and generate data TQs (+ coverage ledger)
    validator = DataValidator(spare_pct=rules_to_use.spare_capacity.spare_percentage)
    valid_signals, data_tqs, ledger = validator.validate(signals, cable_sizes)

    # Step 2: three-stage solve (units -> cabinets -> CIOCs -> slots)
    prevmap = session_state.get("placements_a") if req.use_rev_a_as_hints else None
    result, new_prev, raw = solve_allocation(valid_signals, cable_sizes, rules_to_use,
                                             prev=prevmap)

    # Merge data TQs (validator's richer versions win on duplicate ids)
    seen_ids = {t.id for t in data_tqs}
    result.tqs = data_tqs + [t for t in result.tqs if t.id not in seen_ids]
    # Coverage (S2-8): every input ROW is placed or held by a TQ. Row-based
    # because duplicate rows collapse to one ledger tag (unique-tag math
    # would read 99.8% on a file with one duplicate pair). On solver
    # failure this honestly reads <100 alongside the failure TQs.
    placed_tags = {s.tag for s in result.allocations if s.tag}
    held_tags = {t for t, v in ledger.items() if v.startswith("held:")}
    accounted_rows = sum(1 for s in signals if s.tag in placed_tags or s.tag in held_tags)
    total_in = len(signals)
    result.coverage_pct = round(100.0 * accounted_rows / max(1, total_in), 1)

    # Independent verification on the WRITTEN file (P2-4): every allocation
    # result carries a checker report derived from the export, not memory.
    waived_groups = {t.id[len("TQ-CAP-"):] for t in result.tqs if t.id.startswith("TQ-CAP-")}
    try:
        violations, waived, export_bytes, ohash = _verify_on_export(
            result.allocations, valid_signals, cable_sizes, rules_to_use,
            held_tags, waived_groups)
        result.violations = violations
        result.waived_count = waived
        result.success = len(violations) == 0
        session_state["last_export"] = export_bytes
        session_state["last_export_hash"] = ohash
        session_state["last_held_tags"] = sorted(held_tags)
        session_state["last_waived_groups"] = sorted(waived_groups)
        session_state["last_sizes"] = dict(cable_sizes)
    except Exception as e:
        result.tqs.append(TQ(
            id="TQ-EXPORT-01", kind="data", items=[], tags=[], rows=[],
            rule_ids=[], message=f"Export verification failed: {e}.",
            options=["Retry the allocation; the template writer is under test (P2-3)."]))

    if req.use_rev_a_as_hints:
        session_state["alloc_b"] = result
        session_state["placements_b"] = new_prev
        session_state["rows_b"] = raw.get("rows", [])
    else:
        session_state["alloc_a"] = result
        session_state["placements_a"] = new_prev
        session_state["rows_a"] = raw.get("rows", [])

    return result.model_dump()

@app.get("/api/explain/{tag}")
def explain_signal_here(tag: str):
    """W2: why is this signal placed where it is? Deterministic, rule-checked."""
    from app.engine.explain import explain_signal
    signals = session_state.get("signals_a") or []
    alloc = session_state.get("alloc_a")
    if not signals or not alloc:
        raise HTTPException(status_code=400, detail="Run an allocation first")
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "",
                "seg": s.seg or ""} for s in signals]
    alloc_rows = [a.model_dump() for a in alloc.allocations]
    held = frozenset(session_state.get("last_held_tags", []))
    return explain_signal(tag, io_rows, alloc_rows, current_rules, held)


class WhatIfRequest(BaseModel):
    kind: str = "add_signal"  # 'add_signal' | 'rule_change' | 'spare_change'
    signals_extra: List[Dict[str, Any]] = []
    rules: Optional[Dict[str, Any]] = None
    spare_percentage: Optional[float] = None


@app.post("/api/what-if")
def what_if(req: WhatIfRequest):
    """W1: score a hypothetical WITHOUT committing it to the session.

    Recomputes in isolation from the committed signals and rules and reports the
    delta. Never mutates session_state.
    """
    from app.engine.rules.loader import validate_document, RuleSchemaError
    signals = session_state.get("signals_a") or []
    if not signals:
        raise HTTPException(status_code=400, detail="Run an allocation first")
    base = session_state.get("alloc_a")
    sizes = dict(session_state.get("last_sizes", {}))

    hypo_rules = current_rules
    if req.rules is not None:
        errors = validate_document(req.rules)
        if errors:
            raise HTTPException(status_code=400, detail={"schema_errors": errors})
        hypo_rules = RuleSetConfig.model_validate(req.rules)
    if req.spare_percentage is not None and req.rules is None:
        hypot = current_rules.model_dump()
        hypot["spare_capacity"]["spare_percentage"] = req.spare_percentage
        hypo_rules = RuleSetConfig.model_validate(hypot)

    extra = [Signal(**{k: v for k, v in d.items() if k in Signal.__dataclass_fields__})
             for d in req.signals_extra]
    for e in extra:
        sizes.setdefault(e.cable, max(e.pair, 12))
    hypo_signals = list(signals) + extra

    v = DataValidator(spare_pct=hypo_rules.spare_capacity.spare_percentage)
    valid, data_tqs, ledger = v.validate(hypo_signals, sizes)
    res, _prev, _raw = solve_allocation(valid, sizes, hypo_rules)
    held = {t for t, val in ledger.items() if val.startswith("held:")}
    held |= {t for q_ in res.tqs for t in (q_.items or ())}
    placed = {s.tag for s in res.allocations if s.tag}
    accounted = sum(1 for s in hypo_signals if s.tag in placed or s.tag in held)
    coverage = round(100.0 * accounted / max(1, len(hypo_signals)), 1)

    added_locations = []
    extra_ids = {e.tag for e in extra}
    for a in res.allocations:
        if a.tag in extra_ids:
            added_locations.append({"tag": a.tag, "location":
                                    f"CAB-{a.cabinet + 1:02d} / CIOC-{a.cioc} / BP-{a.baseplate} / S-{a.slot}",
                                    "charm": a.charm})

    base_cabs = base.cabinets_used if base else None
    base_cov = base.coverage_pct if base else None
    delta_cabs = (res.cabinets_used - base_cabs) if base_cabs is not None else None
    return {
        "kind": req.kind,
        "committed": False,
        "base": {"cabinets_used": base_cabs, "coverage_pct": base_cov},
        "hypothetical": {
            "cabinets_used": res.cabinets_used,
            "coverage_pct": coverage,
            "slots_used": res.slots_used,
            "spare_pct_actual": res.spare_pct_actual,
            "tq_count": len(res.tqs),
        },
        "delta": {"cabinets": delta_cabs, "coverage_pct": round(coverage - base_cov, 1) if base_cov is not None else None},
        "added_locations": added_locations,
        "note": "What-if only. The committed allocation and the session were not modified.",
    }


@app.post("/api/check")
def check_exported():
    """Re-run the independent checker on the last exported workbook bytes."""
    import checker.check as _chk
    from app.engine.solve.bridge import rules_to_ref
    from app.engine.io.template_writer import load_template_map, allocation_hash
    from pathlib import Path as _Path
    data = session_state.get("last_export")
    if not data:
        raise HTTPException(status_code=400, detail="No export yet: allocate first")
    tmap = load_template_map(_Path("data/templates/synthetic_map.yaml"))
    back = _chk.read_workbook_rows(data, {"allocation_sheet": tmap["allocation_sheet"],
                                          "first_data_row": tmap["first_data_row"],
                                          "columns": tmap["columns"]})
    signals = session_state.get("signals_a") or []
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "",
                "seg": s.seg or ""} for s in signals]
    found = _chk.check(io_rows, back, rules_to_ref(current_rules), _hw_table_for(current_rules),
                       session_state.get("last_sizes", {}),
                       frozenset(session_state.get("last_held_tags", [])),
                       frozenset(session_state.get("last_waived_groups", [])))
    real = [v for v in found if v["status"] == "violation"]
    return {"output_hash": session_state.get("last_export_hash"),
            "n_violation": len(real), "n_waived": len(found) - len(real),
            "violations": [{"rule_id": _RULE_ID_MAP.get(v["rule"], v["rule"]),
                            "rule_name": _RULE_ID_MAP.get(v["rule"], v["rule"]),
                            "message": v["message"], "status": v["status"]} for v in real]}


@app.post("/api/checker/plant-violation")
def plant_violation(req: PlantViolationRequest):
    import checker.check as _chk
    from app.engine.io.template_writer import load_template_map
    from pathlib import Path as _Path
    data = session_state.get("last_export")
    if not data:
        raise HTTPException(status_code=400, detail="Run allocation first before planting a violation")
    tmap = load_template_map(_Path("data/templates/synthetic_map.yaml"))
    tmap_small = {"allocation_sheet": tmap["allocation_sheet"],
                  "first_data_row": tmap["first_data_row"], "columns": tmap["columns"]}
    try:
        tampered = _chk.plant_violation(data, tmap_small, req.plant_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    back = _chk.read_workbook_rows(tampered, tmap_small)
    signals = session_state.get("signals_a") or []
    io_rows = [{"tag": s.tag, "io_type": s.io_type, "subtype": s.subtype or "",
                "cable": s.cable, "pair": s.pair, "group": s.group or "",
                "seg": s.seg or ""} for s in signals]
    from app.engine.solve.bridge import rules_to_ref
    found = _chk.check(io_rows, back, rules_to_ref(current_rules), _hw_table_for(current_rules),
                       session_state.get("last_sizes", {}),
                       frozenset(session_state.get("last_held_tags", [])),
                       frozenset(session_state.get("last_waived_groups", [])))
    real = [v for v in found if v["status"] == "violation"]
    return {
        "status": "TAMPERED_FOR_AUDIT_DEMO",
        "plant_type": req.plant_type,
        "violations_detected_by_independent_checker": len(real),
        "violations": [{"rule_id": _RULE_ID_MAP.get(v["rule"], v["rule"]),
                        "rule_name": _RULE_ID_MAP.get(v["rule"], v["rule"]),
                        "message": v["message"], "status": v["status"]} for v in real],
        "tampered_sample_slots": back[:50]
    }

@app.post("/api/revision/generate-b")
def generate_revision_b(add_pct: float = 0.05, del_pct: float = 0.02, type_pct: float = 0.015, recable_pct: float = 0.0):
    signals_a = session_state.get("signals_a")
    if not signals_a:
        gen = SyntheticGenerator(seed=42)
        signals_a, cab_info = gen.generate_dataset(n_signals=1000)
        session_state["signals_a"] = signals_a
        session_state["cables_info_a"] = cab_info
        # Fresh Rev A through the three-stage engine so placements exist
        sizes_a = {c["cable_id"]: c["size"] for c in cab_info}
        res_a, prev_a, raw_a = solve_allocation(signals_a, sizes_a, current_rules)
        session_state["alloc_a"] = res_a
        session_state["placements_a"] = prev_a
        session_state["rows_a"] = raw_a.get("rows", [])

    cables_a = {c["cable_id"]: c["size"] for c in session_state.get("cables_info_a", [])} or None
    gen = SyntheticGenerator(seed=42)
    signals_b, diff_meta = gen.generate_revision_b(
        rev_a_signals=signals_a,
        add_pct=add_pct,
        del_pct=del_pct,
        type_change_pct=type_pct,
        recable_pct=recable_pct,
        cable_sizes=cables_a,
    )

    session_state["signals_b"] = signals_b

    # Rev B via keep literals + measured from-scratch baseline (P2-2 core)
    cable_sizes_b = diff_meta["cable_sizes"]
    validator = DataValidator()
    valid_b, data_tqs_b, _ = validator.validate(signals_b, cable_sizes_b)
    result_b, prev_b, raw_b = solve_revision(
        valid_b, cable_sizes_b, current_rules,
        session_state.get("placements_a") or {},
        signals_a, session_state.get("rows_a") or [],
        to_core_signals(signals_a),
    )
    seen = {t.id for t in data_tqs_b}
    result_b.tqs = data_tqs_b + [t for t in result_b.tqs if t.id not in seen]
    session_state["alloc_b"] = result_b
    session_state["placements_b"] = prev_b
    session_state["rows_b"] = raw_b.get("rows", [])

    return {
        "diff_meta": diff_meta,
        "rev_b_result": result_b.model_dump()
    }

@app.get("/api/bench/latest")
def bench_latest():
    """Benchmark table + chart as written by `make bench` (P5-1)."""
    import json as _json
    from pathlib import Path as _Path
    p = _Path("bench/results.json")
    if not p.exists():
        return {"table": [], "chart": [], "meta": {},
                "empty": "No benchmark run yet: run `make bench`."}
    return _json.loads(p.read_text())


@app.post("/api/revise")
async def revise_uploaded(file: UploadFile = File(...), sheet: Optional[str] = Form(None),
                          overrides_json: Optional[str] = Form(None)):
    """Rev B as a real uploaded file (P2-2): same mapping flow as upload,
    Rev A cable sizes carried unless Rev B's size column changes them,
    keep-literal revision + measured from-scratch baseline + tag-level diff.
    """
    import json as _json
    signals_a = session_state.get("signals_a")
    if not signals_a or not session_state.get("placements_a"):
        raise HTTPException(status_code=400, detail="Allocate Rev A first")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    overrides = _json.loads(overrides_json) if overrides_json else None
    try:
        sh, h_idx, header, mapping, (signals_b, sizes_b_new) = _parse_upload_to_signals(
            raw, file.filename or "rev_b.xlsx", overrides, sheet)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    # Sizes: Rev A carried, Rev B size column wins per cable (S1-4).
    sizes_a = {c["cable_id"]: c["size"] for c in session_state.get("cables_info_a", [])}
    sizes_a.update(session_state.get("last_sizes", {}))
    cable_sizes_b = dict(sizes_a)
    cable_sizes_b.update(sizes_b_new)

    validator = DataValidator()
    valid_b, data_tqs_b, _ = validator.validate(signals_b, cable_sizes_b)
    result_b, prev_b, raw_b = solve_revision(
        valid_b, cable_sizes_b, current_rules,
        session_state.get("placements_a") or {},
        signals_a, session_state.get("rows_a") or [],
        to_core_signals(signals_a),
    )
    seen = {t.id for t in data_tqs_b}
    result_b.tqs = data_tqs_b + [t for t in result_b.tqs if t.id not in seen]

    # Tag-level diff: added / deleted / changed-data / changed-hw / unchanged.
    a_by_tag = {s.tag: s for s in signals_a}
    b_by_tag = {s.tag: s for s in signals_b}
    tags_a, tags_b = set(a_by_tag), set(b_by_tag)
    added = sorted(tags_b - tags_a)
    deleted = sorted(tags_a - tags_b)
    changed_data, changed_hw = [], []
    for t in sorted(tags_a & tags_b):
        a, b = a_by_tag[t], b_by_tag[t]
        if (a.cable, a.pair) != (b.cable, b.pair):
            changed_data.append(t)
        elif (a.io_type, a.subtype or "") != (b.io_type, b.subtype or ""):
            changed_hw.append(t)
    unchanged = sorted(tags_a & tags_b - set(changed_data) - set(changed_hw))

    session_state["signals_b"] = signals_b
    session_state["alloc_b"] = result_b
    session_state["placements_b"] = prev_b
    session_state["rows_b"] = raw_b.get("rows", [])

    return {
        "diff": {"added": added, "deleted": deleted, "changed_data": changed_data,
                 "changed_hw": changed_hw, "unchanged": unchanged},
        "rev_b_result": result_b.model_dump(),
    }

@app.post("/api/benchmark/run")
def run_benchmark(req: BenchmarkRequest):
    gen = SyntheticGenerator(seed=req.seed)
    signals, cables_info = gen.generate_dataset(n_signals=req.signal_count)
    cable_sizes = {c["cable_id"]: c["size"] for c in cables_info}

    # Generate Rev B for comparison (sizes carried from Rev A, never inferred)
    signals_b, diff_meta_b = gen.generate_revision_b(signals, cable_sizes=cable_sizes)
    cable_sizes_b = diff_meta_b["cable_sizes"]

    baselines = BaselineEngine(current_rules)

    # 1. B0 Greedy in file order
    b0_res = baselines.run_b0_file_order(signals, cable_sizes)

    # 2. B1 Greedy grouped & A/B aware
    b1_res = baselines.run_b1_grouped_ab(signals, cable_sizes)

    # 3. CHARMSAT three-stage engine (Rev A fresh, Rev B via keep literals)
    charmsat_res_a, prev_a, raw_a = solve_allocation(signals, cable_sizes, current_rules)
    charmsat_res_b, _, _ = solve_revision(
        signals_b, cable_sizes_b, current_rules, prev_a,
        signals, raw_a.get("rows", []), to_core_signals(signals))

    # Proven lower bound from the engine (max of slot/segregation/solver bounds)
    lower_bound = max(1, raw_a.get("lower_bounds", {}).get("best", 1))

    # Rev B moves for B1 (measured: re-run B1 on Rev B, count moved tags)
    b1_rev_b = baselines.run_b1_grouped_ab(signals_b, cable_sizes_b)
    b0_rev_b = baselines.run_b0_file_order(signals_b, cable_sizes_b)
    # Measured moves: compare each baseline's Rev A vs Rev B allocations tag-by-tag.
    b0_moves = _moves_between(b0_res.allocations, b0_rev_b.allocations)
    b1_moves = _moves_between(b1_res.allocations, b1_rev_b.allocations)
    charmsat_moves = charmsat_res_b.rev_summary.moves_ours if charmsat_res_b.rev_summary else 0

    def _verdict(name, viols, cabs, lb, status=""):
        if viols > 0:
            return "FAIL (Violates Rules)"
        if cabs == lb:
            return "OPTIMAL (matches lower bound)" if not status or status == "OPTIMAL" else f"FEASIBLE (matches lower bound, {status})"
        return f"GAP {cabs - lb} (uses {cabs}, lower bound {lb})"

    results = [
        {
            "engine": "B0 Greedy (File Order)",
            "violations": len(b0_res.violations),
            "cabinets": b0_res.cabinets_used,
            "cabinets_vs_lb": f"{b0_res.cabinets_used} / {lower_bound}",
            "rev_b_moves": b0_moves,
            "runtime_s": round(b0_res.runtime_s, 3),
            "verdict": _verdict("B0", len(b0_res.violations), b0_res.cabinets_used, lower_bound)
        },
        {
            "engine": "B1 Greedy (Grouped + A/B)",
            "violations": len(b1_res.violations),
            "cabinets": b1_res.cabinets_used,
            "cabinets_vs_lb": f"{b1_res.cabinets_used} / {lower_bound}",
            "rev_b_moves": b1_moves,
            "runtime_s": round(b1_res.runtime_s, 3),
            "verdict": _verdict("B1", len(b1_res.violations), b1_res.cabinets_used, lower_bound)
        },
        {
            "engine": "CHARMSAT (CP-SAT Solver)",
            "violations": len(charmsat_res_a.violations),
            "cabinets": charmsat_res_a.cabinets_used,
            "cabinets_vs_lb": f"{charmsat_res_a.cabinets_used} / {lower_bound}",
            "rev_b_moves": charmsat_moves,
            "runtime_s": round(charmsat_res_a.runtime_s, 3),
            "verdict": _verdict("CHARMSAT", len(charmsat_res_a.violations), charmsat_res_a.cabinets_used, lower_bound, charmsat_res_a.solver_status)
        }
    ]

    for r in results:
        storage.save_benchmark(
            run_name=f"Bench-{req.signal_count}",
            count=req.signal_count,
            engine=r["engine"],
            viols=r["violations"],
            cabs=r["cabinets"],
            lb=lower_bound,
            moves=r["rev_b_moves"],
            runtime=r["runtime_s"]
        )

    return {
        "signal_count": req.signal_count,
        "lower_bound_cabinets": lower_bound,
        "benchmark_table": results,
        # Only the point just measured. History across N comes from `make bench`
        # (bench/results.json), never from typed-in constants.
        "runtime_line_chart": [
            {"signals": req.signal_count, "b0": round(b0_res.runtime_s, 3),
             "b1": round(b1_res.runtime_s, 3), "charmsat": round(charmsat_res_a.runtime_s, 3)}
        ]
    }

@app.post("/api/export/excel")
def export_excel():
    """Export into a COPY of the allocation template (P2-3).

    Uses the organiser template when data/organiser/template.xlsx (+ map)
    exists locally, else the clearly labelled synthetic stand-in. Never
    writes into the original. On template failure serves a plain workbook
    whose filename signals the mismatch (MD 10.4).
    """
    import tempfile as _tf
    from pathlib import Path as _Path
    from app.engine.io.template_writer import (
        load_template_map, write_template, write_plain_workbook,
        rows_from_allocations, allocation_hash, TemplateWriteError)
    active_alloc = session_state.get("alloc_a")
    if not active_alloc:
        raise HTTPException(status_code=400, detail="No active allocation to export")

    org_t = _Path("data/organiser/template.xlsx")
    org_m = _Path("data/templates/organiser_map.yaml")
    if org_t.exists() and org_m.exists():
        template, tmap, tname = org_t, load_template_map(org_m), "organiser"
    else:
        template = _Path("data/templates/synthetic_template.xlsx")
        tmap = load_template_map(_Path("data/templates/synthetic_map.yaml"))
        tname = "synthetic"

    rows = rows_from_allocations(active_alloc.allocations)
    ohash = allocation_hash(rows)
    rev = session_state.get("alloc_b").rev_summary if session_state.get("alloc_b") else None
    audit = [["output_hash", ohash], ["template", tname],
             ["cabinets", active_alloc.cabinets_used],
             ["lower_bound", active_alloc.lower_bound_cabinets],
             ["solver_status", active_alloc.solver_status],
             ["runtime_s", active_alloc.runtime_s],
             ["coverage_pct", active_alloc.coverage_pct],
             ["rev_moves_ours", rev.moves_ours if rev else ""],
             ["rev_moves_scratch", rev.moves_from_scratch if rev else ""]]
    tq_grid = [["id", "kind", "tags", "rows", "rules", "message"]] + [
        [t.id, t.kind, ",".join(t.tags or t.items), ",".join(map(str, t.rows)),
         ",".join(t.rule_ids), t.message] for t in active_alloc.tqs]

    with _tf.TemporaryDirectory() as tmp:
        out = _Path(tmp) / "out.xlsx"
        try:
            write_template(template, out, tmap, rows,
                           extras={"TQ_LOG": tq_grid, "AUDIT": audit})
            data = out.read_bytes()
            fname = "CHARMSAT_DeltaV_IO_Allocation.xlsx"
        except TemplateWriteError as e:
            audit.append(["template_warning", str(e)])
            write_plain_workbook(out, rows, active_alloc.tqs, audit)
            data = out.read_bytes()
            fname = "CHARMSAT_PLAIN_Allocation_TemplateMismatch.xlsx"

    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"}
    )

@app.get("/api/demo-init")
def demo_init():
    """
    Initializes a complete seeded 1,000-signal run end-to-end,
    generating Rev A, allocating it with CP-SAT, generating Rev B,
    and verifying zero violations.
    """
    gen = SyntheticGenerator(seed=42)
    sig_a, cab_info_a = gen.generate_dataset(n_signals=1000)
    c_sizes_a = {c["cable_id"]: c["size"] for c in cab_info_a}
    session_state["signals_a"] = sig_a
    session_state["cables_info_a"] = cab_info_a

    res_a, prev_a, raw_a = solve_allocation(sig_a, c_sizes_a, current_rules)
    session_state["alloc_a"] = res_a
    session_state["placements_a"] = prev_a
    session_state["rows_a"] = raw_a.get("rows", [])

    # Generate Rev B (sizes carried from Rev A, never inferred per signal)
    sig_b, diff_meta = gen.generate_revision_b(sig_a, cable_sizes=c_sizes_a)
    session_state["signals_b"] = sig_b
    c_sizes_b = diff_meta["cable_sizes"]

    res_b, prev_b, raw_b = solve_revision(
        sig_b, c_sizes_b, current_rules, prev_a,
        sig_a, raw_a.get("rows", []), to_core_signals(sig_a))
    session_state["alloc_b"] = res_b
    session_state["placements_b"] = prev_b
    session_state["rows_b"] = raw_b.get("rows", [])

    return {
        "status": "DEMO_READY",
        "signals_a_count": len(sig_a),
        "rev_a_success": res_a.success,
        "rev_a_violations": len(res_a.violations),
        "rev_a_cabinets": res_a.cabinets_used,
        "rev_a_runtime": res_a.runtime_s,
        "rev_b_success": res_b.success,
        "rev_b_moves_ours": res_b.rev_summary.moves_ours if res_b.rev_summary else 0,
        "rev_b_moves_scratch": res_b.rev_summary.moves_from_scratch if res_b.rev_summary else 0
    }

# Mount static frontend build if present
dist_folder = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if dist_folder.exists():
    app.mount("/", StaticFiles(directory=str(dist_folder), html=True), name="frontend_dist")

