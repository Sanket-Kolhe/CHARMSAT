from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field
import yaml


class HardwareRow(BaseModel):
    """One row of the hardware table (data, not code): first match wins."""
    io_type: str
    subtype: str = "*"          # "*" matches any subtype
    charm: str
    tb: str


def _default_hardware_table() -> List[HardwareRow]:
    """Default hardware table, mirroring app/engine/hardware.py.

    Kept as data on the rule set (P3) so the whole table can be overridden
    from YAML without a code change; the loader/schema validate it.
    """
    return [
        HardwareRow(io_type="AI", subtype="*", charm="AI 4-20 mA HART", tb="Standard"),
        HardwareRow(io_type="AO", subtype="*", charm="AO 4-20 mA HART", tb="Standard"),
        HardwareRow(io_type="DI", subtype="120VAC", charm="DI 120V AC Isolated", tb="Standard"),
        HardwareRow(io_type="DI", subtype="*", charm="DI 24V DC Low-Side", tb="Standard"),
        HardwareRow(io_type="DO", subtype="HIGH_CURRENT", charm="DO 24V DC Isolated", tb="Fused Injected Power"),
        HardwareRow(io_type="DO", subtype="RELAY", charm="DO 24V DC High-Side", tb="Relay Output"),
        HardwareRow(io_type="DO", subtype="*", charm="DO 24V DC High-Side", tb="Standard"),
        HardwareRow(io_type="RTD", subtype="*", charm="RTD Temperature", tb="RTD TB"),
        HardwareRow(io_type="TC", subtype="*", charm="TC Temperature", tb="Thermocouple TB"),
    ]

class RuleABSegregationConfig(BaseModel):
    id: str = "RULE-01"
    name: str = "A/B Segregation"
    enabled: bool = True
    level: Literal["cioc", "cabinet", "baseplate"] = "cioc"
    description: str = "Segregates Train A and Train B field signals into separate hardware units to eliminate common-cause failure."

class RuleCableContiguityConfig(BaseModel):
    id: str = "RULE-02"
    name: str = "Cable Block Contiguity & Boundary"
    enabled: bool = True
    allow_boundary_crossing_small: bool = False  # False means 6-pair/2-pair cannot cross baseplate boundaries
    strict_pair_ordering: bool = True            # Pairs land in ascending slot order
    description: str = "Treats multi-pair cables as atomic blocks; requires 12/24-pair baseplate alignment and controls small cable straddling."

class RuleGroupCohesionConfig(BaseModel):
    id: str = "RULE-03"
    name: str = "Group Cabinet Cohesion & Sequence"
    enabled: bool = True
    target_level: Literal["cabinet", "cioc"] = "cabinet"
    soft_sequence_weight: int = 5                # Objective penalty weight for breaking signal tag sequence
    description: str = "Groups related instruments (e.g. reactor loops) into the same cabinet with sequential slot preference."

class RuleSpareCapacityConfig(BaseModel):
    id: str = "RULE-04"
    name: str = "Cabinet Spare Capacity Margin"
    enabled: bool = True
    spare_percentage: float = 10.0               # Default 10.0% spare room per cabinet
    description: str = "Reserves expansion capacity per cabinet (max used slots <= floor(384 * (1 - spare%)))."

class RuleIsolatedCharmConfig(BaseModel):
    id: str = "RULE-05"
    name: str = "Isolated CHARM Subtypes"
    enabled: bool = True
    isolated_subtypes: List[str] = Field(default_factory=lambda: ["SOV", "horn", "beacon", "ISOLATED"])
    description: str = "Enforces isolated CHARMs with relay terminal blocks for inductive or high-power DO devices."

class CharmHardwareMap(BaseModel):
    charm: str
    terminal_block: str

class RuleSignalTypeLookupConfig(BaseModel):
    id: str = "RULE-06"
    name: str = "Hardware Type Lookup"
    enabled: bool = True
    mapping: Dict[str, CharmHardwareMap] = Field(default_factory=lambda: {
        "AI": CharmHardwareMap(charm="AI 4-20mA HART", terminal_block="Standard TB"),
        "AO": CharmHardwareMap(charm="AO 4-20mA HART", terminal_block="Standard TB"),
        "DI": CharmHardwareMap(charm="DI 24V DC Dry Contact", terminal_block="Standard TB"),
        # PDS-correct pairings (P1-4). The solver/checker use engine/hardware.py;
        # this dict is kept for UI display until the YAML rule language (P3).
        "DO": CharmHardwareMap(charm="DO 24V DC High-Side", terminal_block="Standard"),
        "DO_HIGH_CURRENT": CharmHardwareMap(charm="DO 24V DC Isolated", terminal_block="Fused Injected Power"),
        "DO_RELAY": CharmHardwareMap(charm="DO 24V DC High-Side", terminal_block="Relay Output"),
        "DO_ISOLATED": CharmHardwareMap(charm="DO 24V DC Isolated", terminal_block="Fused Injected Power"),
        "RTD": CharmHardwareMap(charm="RTD Temperature", terminal_block="RTD TB"),
        "TC": CharmHardwareMap(charm="TC Temperature", terminal_block="Thermocouple TB")
    })
    description: str = "Deterministic lookup mapping electrical signal types to Emerson DeltaV CHARM hardware and terminal blocks."

class RuleNamingPatternsConfig(BaseModel):
    id: str = "RULE-07"
    name: str = "Asset Naming Patterns"
    enabled: bool = True
    # Token patterns (P1-6; tokens documented in engine/naming.py).
    # Defaults reproduce both PS examples (blueprint 7.4).
    cabinet: str = "CAB-{cab:02}"
    cioc: str = "AR{area}CIOC{cab}{cioc_global:05}"
    baseplate: str = "{cioc_global:03}-CBP-{bp}"
    charm: str = "{baseplate_name}-{slot:02}"
    area: str = "1"
    description: str = "Token-based asset naming. Tokens: area, cab, cioc, cioc_global, bp, bp_global, slot, cab_name, cioc_name, baseplate_name. Unknown tokens are rejected at load."

class GenericRuleConfig(BaseModel):
    id: str
    name: str = ""
    enabled: bool = True
    relation: Literal["same", "different", "at_most_k"]
    attribute: Literal["group", "seg", "io_type", "subtype"]
    level: Literal["cabinet", "cioc", "baseplate"]
    k_value: int = 1
    # For relation "different": the values that must never share a unit.
    # Empty/None means "every distinct value is its own class" (ALL_DISTINCT),
    # which is the natural reading of "never share with a different <attribute>".
    classes: Optional[List[str]] = None
    description: str = ""

class RuleSetConfig(BaseModel):
    ab_segregation: RuleABSegregationConfig = Field(default_factory=RuleABSegregationConfig)
    cable_contiguity: RuleCableContiguityConfig = Field(default_factory=RuleCableContiguityConfig)
    group_cohesion: RuleGroupCohesionConfig = Field(default_factory=RuleGroupCohesionConfig)
    spare_capacity: RuleSpareCapacityConfig = Field(default_factory=RuleSpareCapacityConfig)
    isolated_charm: RuleIsolatedCharmConfig = Field(default_factory=RuleIsolatedCharmConfig)
    signal_type_lookup: RuleSignalTypeLookupConfig = Field(default_factory=RuleSignalTypeLookupConfig)
    naming_patterns: RuleNamingPatternsConfig = Field(default_factory=RuleNamingPatternsConfig)
    # Hardware table as data (P3). Empty list = use the in-code default.
    hardware_table: List[HardwareRow] = Field(default_factory=_default_hardware_table)
    custom_rules: List[GenericRuleConfig] = Field(default_factory=list)

    def to_yaml(self) -> str:
        return yaml.dump(self.model_dump(), sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "RuleSetConfig":
        # Validate against the JSON schema first (P3), then build the model.
        from app.engine.rules.loader import load_rule_set
        return load_rule_set(yaml_str)
