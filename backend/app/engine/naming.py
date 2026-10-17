"""Token-based asset naming (P1-6).

Patterns use tokens; values are 1-based in the output:
  {area} {cab} {cioc} {cioc_global} {bp} {bp_global} {slot}
  {cab_name} {cioc_name} {baseplate_name}
Format specs work: {cioc_global:05}, {cab:02}, {slot:02}.
Composition order: cabinet -> cioc -> baseplate -> charm, so later
patterns may reference earlier names.

Defaults reproduce both PS examples (blueprint 7.4):
  cabinet "CAB-{cab:02}" with cab=1                       -> CAB-01
  cioc "AR{area}CIOC{cab}{cioc_global:05}" (area=1)        -> AR1CIOC100001
  baseplate "{cioc_global:03}-CBP-{bp}"                    -> 001-CBP-1
  charm "{baseplate_name}-{slot:02}"                       -> 001-CBP-1-07

Unknown tokens raise ValueError at load time (rule-load validation).
"""
import string
from typing import Tuple

ALLOWED_TOKENS = frozenset({
    "area", "cab", "cioc", "cioc_global", "bp", "bp_global", "slot",
    "cab_name", "cioc_name", "baseplate_name",
})


def validate_pattern(pattern: str, what: str) -> None:
    """Raise ValueError naming any unknown token (called at rule-load time)."""
    for _, field, _, _ in string.Formatter().parse(pattern):
        if field is None:
            continue
        name = field.split("!")[0].split(":")[0].split(".")[0].split("[")[0]
        if name and name not in ALLOWED_TOKENS:
            raise ValueError(
                f"Unknown token {{{name}}} in {what} pattern {pattern!r}. "
                f"Allowed: {sorted(ALLOWED_TOKENS)}"
            )


class NameGenerator:
    def __init__(self, config):
        self.config = config
        self.area = getattr(config, "area", "1") or "1"
        for what in ("cabinet", "cioc", "baseplate", "charm"):
            validate_pattern(getattr(config, what), f"naming.{what}")

    def _tokens(self, cabinet_idx: int, cioc_idx: int, baseplate_idx: int,
                slot_1based: int = 1, cab_name: str = "", cioc_name: str = "",
                baseplate_name: str = "") -> dict:
        return {
            "area": self.area,
            "cab": cabinet_idx + 1,
            "cioc": cioc_idx + 1,
            "cioc_global": cabinet_idx * 4 + cioc_idx + 1,
            "bp": baseplate_idx + 1,
            "bp_global": cabinet_idx * 32 + cioc_idx * 8 + baseplate_idx + 1,
            "slot": slot_1based,
            "cab_name": cab_name,
            "cioc_name": cioc_name,
            "baseplate_name": baseplate_name,
        }

    def get_names(self, cabinet_idx: int, cioc_idx: int, baseplate_idx: int) -> Tuple[str, str, str]:
        """(cabinet_name, cioc_name, baseplate_name); all indices 0-based in."""
        t = self._tokens(cabinet_idx, cioc_idx, baseplate_idx)
        cab_name = self.config.cabinet.format(**t)
        t["cab_name"] = cab_name
        cioc_name = self.config.cioc.format(**t)
        t["cioc_name"] = cioc_name
        baseplate_name = self.config.baseplate.format(**t)
        return cab_name, cioc_name, baseplate_name

    def charm_name(self, cabinet_idx: int, cioc_idx: int, baseplate_idx: int,
                   slot_1based: int) -> str:
        """Asset name of one CHARM slot (slot_1based: 1..12)."""
        cab_name, cioc_name, baseplate_name = self.get_names(cabinet_idx, cioc_idx, baseplate_idx)
        t = self._tokens(cabinet_idx, cioc_idx, baseplate_idx, slot_1based,
                         cab_name, cioc_name, baseplate_name)
        return self.config.charm.format(**t)
