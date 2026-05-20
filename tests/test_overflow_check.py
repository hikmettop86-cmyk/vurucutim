"""Real Playwright integration — slow but the only honest check."""
import pytest

from short_bot.overflow import check_overflow

pytestmark = pytest.mark.slow  # mark per pyproject.toml markers


def _wrap(body_html: str, archetype_css: str = "") -> str:
    """Minimal newscast-shape HTML stub for unit-level overflow tests.

    We don't load the real template here — we craft just enough DOM
    (.header .top, .header .bot, .photo .yellow, .body) for the measurement
    JS to find selectors. The real templates are exercised in the matrix.
    """
    return f"""<!DOCTYPE html>
<html><head><style>
  *{{box-sizing:border-box;margin:0;padding:0;}}
  html,body{{width:1080px;height:1920px;overflow:hidden;background:#000;
    font-family:Inter,sans-serif;color:#fff;}}
  .stage{{width:1080px;height:1920px;position:relative;}}
  .header{{padding:78px 60px 44px;font-size:100px;line-height:1.02;
    text-align:center;}}
  .header .top{{display:block;}}
  .header .bot{{display:block;margin-top:8px;}}
  .photo{{height:640px;background:#222;position:relative;}}
  .photo .yellow{{position:absolute;bottom:40px;left:0;right:0;
    font-size:64px;line-height:1.05;padding:28px 50px;text-align:center;
    background:#ffea3b;color:#000;}}
  .body{{padding:50px 60px 30px;font-size:48px;line-height:1.42;
    -webkit-line-clamp:9;-webkit-box-orient:vertical;display:-webkit-box;
    overflow:hidden;}}
  {archetype_css}
</style></head>
<body><div class="stage">
  <div class="header"><span class="top"></span><span class="bot"></span></div>
  <div class="photo"><div class="yellow"></div></div>
  <div class="body"></div>
</div>
{body_html}
</body></html>"""


def _set_text(html: str, selector: str, text: str) -> str:
    """Inject text into the matching <span class=...></span> by string replace."""
    if selector == ".header .top":
        return html.replace('<span class="top"></span>',
                            f'<span class="top">{text}</span>')
    if selector == ".header .bot":
        return html.replace('<span class="bot"></span>',
                            f'<span class="bot">{text}</span>')
    if selector == ".photo .yellow":
        return html.replace('<div class="yellow"></div>',
                            f'<div class="yellow">{text}</div>')
    if selector == ".body":
        return html.replace('<div class="body"></div>',
                            f'<div class="body">{text}</div>')
    raise ValueError(selector)


def test_short_text_no_overflow():
    html = _wrap("")
    html = _set_text(html, ".header .top", "ARA ZAM")
    html = _set_text(html, ".header .bot", "GELDI MI?")
    html = _set_text(html, ".photo .yellow", "MILYONLAR BEKLIYOR")
    html = _set_text(html, ".body", "Kisa bir govde yazisi. Iki cumle yeter. " * 2)

    report = check_overflow(html, archetype="newscast")
    assert report.has_any_overflow() is False, report.summary()


def test_long_header_top_overflows():
    html = _wrap("")
    long_header = "BU COK UZUN BIR BASLIK VE KESINLIKLE TASMA YAPACAK BURADA"
    html = _set_text(html, ".header .top", long_header)
    html = _set_text(html, ".header .bot", "OK")
    html = _set_text(html, ".photo .yellow", "OK")
    html = _set_text(html, ".body", "Kisa govde. " * 5)

    report = check_overflow(html, archetype="newscast")
    assert report.has_any_overflow() is True
    assert report.fields["header_top"].has_overflow is True
    assert report.fields["header_top"].current_chars == len(long_header)
    assert report.fields["header_top"].recommended_max_chars < len(long_header)


def test_body_budget_is_intentionally_generous_to_avoid_spurious_retries():
    """2026-05-19: body_paragraph budget across all archetypes raised to 99
    (commit 06237c5) so DNA custom_css scrollHeight measurement quirks don't
    trigger truncate '…' UX. The CSS line-clamp still cuts visually; the
    overflow check just no longer flags it. This test pins the decision."""
    html = _wrap("")
    html = _set_text(html, ".header .top", "OK")
    html = _set_text(html, ".header .bot", "OK")
    html = _set_text(html, ".photo .yellow", "OK")
    very_long_body = "Bu cok uzun bir govde. " * 80
    html = _set_text(html, ".body", very_long_body)

    report = check_overflow(html, archetype="newscast")
    assert report.fields["body_paragraph"].has_overflow is False
    assert report.fields["body_paragraph"].max_lines == 99


def test_unknown_archetype_raises_keyerror():
    with pytest.raises(KeyError):
        check_overflow("<html></html>", archetype="not-a-real-archetype")
