import pytest

from short_bot.templates_config import (
    OverflowField,
    ARCHETYPE_OVERFLOW_FIELDS,
)


ARCHETYPES = ["newscast", "stadium", "stat-hero", "bigquote", "polaroid"]


def test_all_archetypes_have_config():
    for a in ARCHETYPES:
        assert a in ARCHETYPE_OVERFLOW_FIELDS, f"{a} missing from config"


def test_every_field_has_non_empty_selector_and_positive_max_lines():
    for archetype, fields in ARCHETYPE_OVERFLOW_FIELDS.items():
        assert len(fields) >= 2, f"{archetype}: at least 2 fields expected"
        for f in fields:
            assert f.name, f"{archetype}: empty name"
            assert f.selector, f"{archetype}: empty selector for {f.name}"
            assert f.max_lines >= 1, f"{archetype}/{f.name}: max_lines must be ≥1"


def test_field_names_are_subset_of_script_fields():
    valid = {"header_top", "header_bottom", "photo_overlay", "body_paragraph"}
    for archetype, fields in ARCHETYPE_OVERFLOW_FIELDS.items():
        for f in fields:
            assert f.name in valid, f"{archetype}: unknown field name {f.name}"


def test_overflow_field_is_frozen():
    import dataclasses
    f = OverflowField("header_top", ".header .top", 2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.max_lines = 99  # frozen dataclass should reject
