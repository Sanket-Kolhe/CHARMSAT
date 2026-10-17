"""Hardware table as DATA (P1-4), not code.

First match wins: (io_type, subtype) -> (CHARM, terminal block).
Pairings per Emerson DeltaV Electronic Marshalling PDS (see blueprint 2.1):
  - normal DO            -> DO 24V DC High-Side + Standard TB
  - DO high-current      -> DO 24V DC Isolated + Fused Injected Power TB
  - DO relay             -> DO 24V DC High-Side + Relay Output TB
The old code had normal->Fused and isolated->Relay backwards.

Subtype vocabulary (blueprint A14) is normalised through SUBTYPE_SYNONYMS;
text with no match returns None and the caller must raise a hardware TQ.

Extensions beyond blueprint 7.4 (kept for compat, flagged):
  - DI 120VAC row: from reference/charmsat_core.py (AC/DC demo data).
  - horn/beacon/isolated -> HIGH_CURRENT: the repo generator emits these
    subtypes for inductive loads; P3 moves the whole table to YAML.
  - RTD/TC rows: pre-existing repo mapping, kept so valid data keeps working.
"""
from typing import Dict, Optional, Tuple

HW_TABLE = [
    {"io_type": "AI", "subtype": "*", "charm": "AI 4-20 mA HART", "tb": "Standard"},
    {"io_type": "AO", "subtype": "*", "charm": "AO 4-20 mA HART", "tb": "Standard"},
    {"io_type": "DI", "subtype": "120VAC", "charm": "DI 120V AC Isolated", "tb": "Standard"},
    {"io_type": "DI", "subtype": "*", "charm": "DI 24V DC Low-Side", "tb": "Standard"},
    {"io_type": "DO", "subtype": "HIGH_CURRENT", "charm": "DO 24V DC Isolated", "tb": "Fused Injected Power"},
    {"io_type": "DO", "subtype": "RELAY", "charm": "DO 24V DC High-Side", "tb": "Relay Output"},
    {"io_type": "DO", "subtype": "*", "charm": "DO 24V DC High-Side", "tb": "Standard"},
    {"io_type": "RTD", "subtype": "*", "charm": "RTD Temperature", "tb": "RTD TB"},
    {"io_type": "TC", "subtype": "*", "charm": "TC Temperature", "tb": "Thermocouple TB"},
]

# Raw subtype text -> canonical subtype (blueprint 7.4 synonyms + repo extensions).
SUBTYPE_SYNONYMS: Dict[str, str] = {
    "": "",
    "NORMAL": "",
    "HIGH_CURRENT": "HIGH_CURRENT",
    "HI CURRENT": "HIGH_CURRENT",
    "HIGH CURRENT": "HIGH_CURRENT",
    "HICURRENT": "HIGH_CURRENT",
    "RELAY": "RELAY",
    "SOV": "",              # blueprint 7.4: sov -> normal
    "HORN": "HIGH_CURRENT",  # repo extension: inductive loads need isolation
    "BEACON": "HIGH_CURRENT",
    "ISOLATED": "HIGH_CURRENT",
}


def normalise_subtype(raw: Optional[str]) -> Optional[str]:
    """Canonical subtype, or None if the text is unknown (caller raises TQ)."""
    if raw is None:
        return ""
    key = " ".join(str(raw).strip().upper().split())
    return SUBTYPE_SYNONYMS.get(key)


def hardware_for(io_type: Optional[str], subtype: Optional[str],
                 table: Optional[list] = None) -> Tuple[Optional[str], Optional[str]]:
    """First matching row wins. (None, None) means no rule matches -> hardware TQ.

    `table` may be supplied from the rule set (P3, data-driven); it is a list
    of dicts with keys io_type/subtype/charm/tb. Falls back to HW_TABLE.
    """
    if not io_type:
        return None, None
    iot = str(io_type).strip().upper()
    sub = normalise_subtype(subtype)
    if sub is None:
        return None, None
    for row in (HW_TABLE if table is None else table):
        if row["io_type"] == iot and row["subtype"] in ("*", sub):
            return row["charm"], row["tb"]
    return None, None
