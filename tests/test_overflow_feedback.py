from short_bot.overflow import FieldOverflow, OverflowReport, format_feedback


def _f(name, overflow, cur=0, lines=1, max_lines=2, rec=0):
    return FieldOverflow(
        name=name, has_overflow=overflow,
        current_chars=cur, current_lines=lines,
        max_lines=max_lines, recommended_max_chars=rec,
    )


def test_no_overflow_returns_empty():
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _f("header_top", overflow=False),
    })
    assert format_feedback(r) == ""


def test_single_overflow_field_listed_with_chars_and_lines():
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _f("header_top", overflow=True, cur=26, lines=3,
                          max_lines=2, rec=14),
        "photo_overlay": _f("photo_overlay", overflow=False, cur=20),
    })
    s = format_feedback(r)
    assert "PREVIOUS ATTEMPT" in s
    assert "header_top" in s
    assert "26" in s and "14" in s
    assert "2" in s   # max_lines=2 mentioned
    # Non-overflow fields not listed in the overflow section:
    assert "photo_overlay" not in s.split("Other fields")[0]


def test_other_fields_called_out_to_be_kept():
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _f("header_top", overflow=True, cur=26, rec=14),
        "header_bottom": _f("header_bottom", overflow=False),
        "body_paragraph": _f("body_paragraph", overflow=False),
    })
    s = format_feedback(r)
    assert "Other fields" in s or "keep them" in s.lower()
    assert "header_bottom" in s and "body_paragraph" in s
