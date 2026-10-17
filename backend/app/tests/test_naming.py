"""P1-6: token-based naming patterns."""
import pytest

from app.engine.naming import NameGenerator, validate_pattern
from app.models.rules import RuleNamingPatternsConfig


def test_ps_examples_reproduced():
    """Blueprint 7.4: cabinet 1, CIOC 1, baseplate 1 -> AR1CIOC100001, 001-CBP-1."""
    gen = NameGenerator(RuleNamingPatternsConfig())
    cab, cioc, bp = gen.get_names(0, 0, 0)
    assert cab == "CAB-01"
    assert cioc == "AR1CIOC100001"
    assert bp == "001-CBP-1"
    assert gen.charm_name(0, 0, 0, 7) == "001-CBP-1-07"


def test_numbering_across_cabinets():
    gen = NameGenerator(RuleNamingPatternsConfig())
    cab, cioc, bp = gen.get_names(1, 3, 7)
    assert cab == "CAB-02"
    assert cioc == "AR1CIOC200008"  # cab=2, cioc_global=8 -> "2"+"00008"
    assert bp == "008-CBP-8"


def test_custom_patterns_and_tokens():
    cfg = RuleNamingPatternsConfig(
        cabinet="CAB-{cab:02}",
        cioc="{cab_name}-CIOC-{cioc:02d}",
        baseplate="{cioc_name}/BP{bp}",
        charm="{bp_global:03}-{slot:02}",
        area="1",
    )
    gen = NameGenerator(cfg)
    cab, cioc, bp = gen.get_names(0, 1, 2)
    assert cab == "CAB-01"
    assert cioc == "CAB-01-CIOC-02"
    assert bp == "CAB-01-CIOC-02/BP3"
    assert gen.charm_name(0, 1, 2, 5) == "011-05"  # bp_global=11


def test_unknown_token_rejected_at_load():
    with pytest.raises(ValueError, match="ciooc"):
        NameGenerator(RuleNamingPatternsConfig(cioc="CIOC-{ciooc}"))
    with pytest.raises(ValueError, match="Unknown token"):
        validate_pattern("{cabinet_no}", "naming.cabinet")


def test_format_specs_supported():
    gen = NameGenerator(RuleNamingPatternsConfig(cioc="C{cioc_global:05}"))
    _, cioc, _ = gen.get_names(0, 0, 0)
    assert cioc == "C00001"
