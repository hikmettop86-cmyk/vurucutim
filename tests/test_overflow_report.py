from short_bot.overflow import FieldOverflow, OverflowReport


def _f(name="header_top", overflow=False, cur=10, lines=1, max_lines=2, rec=10):
    return FieldOverflow(
        name=name, has_overflow=overflow,
        current_chars=cur, current_lines=lines,
        max_lines=max_lines, recommended_max_chars=rec,
    )


def test_has_any_overflow_false_when_all_clean():
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _f(),
        "body_paragraph": _f(name="body_paragraph"),
    })
    assert r.has_any_overflow() is False


def test_has_any_overflow_true_when_one_field_overflows():
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _f(),
        "photo_overlay": _f(name="photo_overlay", overflow=True, cur=48, rec=32),
    })
    assert r.has_any_overflow() is True


def test_summary_lists_only_overflowing_fields():
    r = OverflowReport(archetype="newscast", fields={
        "header_top": _f(overflow=True, cur=26, rec=14),
        "header_bottom": _f(name="header_bottom"),
        "photo_overlay": _f(name="photo_overlay", overflow=True, cur=48, rec=32),
    })
    s = r.summary()
    assert "header_top" in s and "26" in s and "14" in s
    assert "photo_overlay" in s and "48" in s and "32" in s
    assert "header_bottom" not in s


def test_summary_clean_when_no_overflow():
    r = OverflowReport(archetype="newscast", fields={"header_top": _f()})
    assert "clean" in r.summary().lower()
