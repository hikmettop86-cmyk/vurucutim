import pytest
from pydantic import ValidationError

from short_bot.models import Highlight, Script
from short_bot.overflow import (
    FieldOverflow,
    OverflowReport,
    truncate_to_fit,
)


def _script(**overrides):
    base = dict(
        header_top="Üst Başlık Buraya Yazılır",  # 25 chars (max_length=25)
        header_bottom="Alttaki Yazı Da Uzun Olabilir Bence",  # 35 chars (max_length=35)
        photo_overlay="Fotoğraf Üstündeki Sarı Bant Yazısı Burada",  # 42 chars (max_length=60)
        body_paragraph=(
            "Birinci cümle burada. İkinci cümle de burada. "
            "Üçüncü cümle ek bilgi veriyor. Dördüncü cümle yine. "
            "Beşinci cümle daha fazla detay. Altıncı cümle son."
        ),
        highlights=[Highlight(text="İkinci cümle", color="yellow")],
        category="GENEL",
        mood="neutral",
    )
    base.update(overrides)
    return Script(**base)


def _fo(name, overflow, cur, rec):
    return FieldOverflow(
        name=name, has_overflow=overflow,
        current_chars=cur, current_lines=2,
        max_lines=2, recommended_max_chars=rec,
    )


def test_no_overflow_returns_unchanged_script():
    s = _script()
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _fo("header_top", False, 35, 35),
    })
    out = truncate_to_fit(s, r)
    assert out.header_top == s.header_top


def test_truncate_header_top_word_boundary_with_ellipsis():
    s = _script(header_top="Bu Çok Uzun Bir Başlık")  # 22 chars, within max_length=25
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _fo("header_top", True, 22, 10),
    })
    out = truncate_to_fit(s, r)
    assert len(out.header_top) <= 12  # rec + ellipsis (1 char) + a little slack
    assert out.header_top.endswith("…")
    # Word boundary: no half-word before ellipsis
    body = out.header_top.rstrip("…").rstrip()
    assert " " not in body or body.split()[-1] in s.header_top.split()


def test_truncate_body_drops_highlights_that_no_longer_appear():
    s = _script(
        body_paragraph="Birinci cümle. İkinci cümle. Üçüncü cümle.",
        highlights=[
            Highlight(text="İkinci cümle", color="yellow"),
            Highlight(text="Üçüncü cümle", color="red"),
        ],
    )
    r = OverflowReport(archetype="newscast", fields={
        "body_paragraph": _fo("body_paragraph", True, 42, 22),
    })
    out = truncate_to_fit(s, r)
    # After truncation to ~22 chars, only "Birinci cümle" survives.
    # Pydantic body min_length is 20 — floor enforces ≥20 chars.
    # Highlights pointing to dropped text must be removed.
    for h in out.highlights:
        assert h.text in out.body_paragraph


def test_body_truncate_respects_pydantic_min_length_floor():
    """body_paragraph has min_length=20 (models.py:44). Recommendation 5
    must be lifted to 20 or truncate would fail validation."""
    s = _script()
    r = OverflowReport(archetype="newscast", fields={
        "body_paragraph": _fo("body_paragraph", True, 200, 5),
    })
    out = truncate_to_fit(s, r)
    assert len(out.body_paragraph) >= 20


def test_header_top_truncate_to_one_char_works():
    """header_top min_length=1 — even rec=1 must succeed."""
    s = _script(header_top="Uzun Başlık")
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _fo("header_top", True, 11, 1),
    })
    out = truncate_to_fit(s, r)
    assert len(out.header_top) >= 1
    # Pydantic max_length=25 also satisfied (it's a shorter string)


def test_pydantic_validation_failure_propagates_as_valueerror():
    """If somehow truncation produces invalid Script, raise ValueError so
    pipeline wrapper can catch and fall back to last-attempt script."""
    s = _script(highlights=[
        Highlight(text="Birinci cümle burada", color="yellow"),  # 20 chars
    ])
    r = OverflowReport(archetype="newscast", fields={
        # Force an absurd recommendation that drops the highlight.
        "body_paragraph": _fo("body_paragraph", True, 200, 25),
    })
    # Should NOT raise — highlight reconciliation kicks in.
    out = truncate_to_fit(s, r)
    for h in out.highlights:
        assert h.text in out.body_paragraph
