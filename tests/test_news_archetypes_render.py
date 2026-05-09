"""Render-smoke tests for news archetype templates.

Each archetype gets one test verifying the template renders without errors
and contains expected DOM markers. Tests added incrementally as templates land.
"""
from pathlib import Path

from short_bot.models import RenderJob, Script
from short_bot.renderer import build_html


def _make_script(language="tr", **overrides):
    """Default Script that satisfies all Pydantic validators."""
    base = dict(
        header_top="ARA ZAM",
        header_bottom="GELDİ Mİ?",
        photo_overlay="MİLYONLAR BEKLİYOR",
        body_paragraph=(
            "Asgari ücrete temmuzda ara zam gelip gelmeyeceği milyonlarca "
            "çalışanı yakından ilgilendiriyor."
        ),
        category="EKONOMİ",
        mood="neutral",
        highlights=[],
    )
    base.update(overrides)
    return Script(**base)


def _make_job(language="tr", colors=None):
    return RenderJob(
        script=_make_script(language=language),
        bg_image_path=None,
        music_path=Path("dummy.mp3"),
        channel_colors=colors or {
            "primary": "#cc0000", "accent": "#ffea3b",
            "bg_gradient": ["#1a1a2a", "#0a0a1a"],
        },
        handle="@test",
        duration_s=30,
        language=language,
        cta_enabled=False,
    )


def _render(archetype: str) -> str:
    template_path = (Path(__file__).resolve().parent.parent
                     / "templates" / f"{archetype}.html.j2")
    return build_html(_make_job(), template_path)


def test_politika_renders():
    html = _render("politika")
    assert 'class="stage' in html
    assert "ARA ZAM" in html
    assert "MİLYONLAR" in html.upper()
    # Politika-specific: serif headline + source overlay class
    assert "Source Serif" in html or "serif" in html.lower()
    assert 'class="source"' in html


def test_ekonomi_renders():
    html = _render("ekonomi")
    assert 'class="stage' in html
    assert "ARA ZAM" in html
    # Ekonomi-specific: ticker bar + JetBrains Mono numerals
    assert "JetBrains Mono" in html
    assert 'class="ticker"' in html or 'class="ticker-num"' in html


def test_spor_haber_renders():
    html = _render("spor-haber")
    assert 'class="stage' in html
    assert "ARA ZAM" in html  # default header still rendered (inside photo overlay)
    assert "Oswald" in html
    assert 'class="stats"' in html


def test_tech_haber_renders_with_white_background():
    html = _render("tech-haber")
    assert 'class="stage' in html
    assert "ARA ZAM" in html
    # Tech-haber-specific: white background
    assert "#ffffff" in html or "#fff" in html.lower()
    assert 'class="tech-tag"' in html
    # Distinguishing: dark text on light bg
    assert "#1d1d1f" in html


def test_hava_durumu_renders_with_temperature():
    html = _render("hava-durumu")
    assert 'class="stage' in html
    # Hava-durumu specifically: city kicker + forecast strip
    assert "ARA ZAM" in html  # default header_top still rendered (as temp)
    assert 'class="city"' in html
    assert 'class="forecast-strip"' in html


def test_yerel_renders_with_warm_palette():
    html = _render("yerel")
    assert 'class="stage' in html
    assert "ARA ZAM" in html
    assert "Playfair" in html
    assert 'class="locale-pin"' in html
    # Cream background
    assert "#fef3e2" in html or "#fdf6e3" in html


def test_gundem_renders():
    html = _render("gundem")
    assert 'class="stage' in html


def test_gundem_renders_body_as_numbered_list():
    """body_paragraph='1. A\\n2. B\\n3. C' must produce 3 list items."""
    job = _make_job()
    job.script = _make_script(
        body_paragraph="1. Birinci başlık burada\n2. İkinci başlık ek\n3. Üçüncü başlık son",
    )
    template_path = (Path(__file__).resolve().parent.parent
                     / "templates" / "gundem.html.j2")
    html = build_html(job, template_path)
    # Three list items present
    assert html.count('class="list-item"') == 3
    assert "Birinci başlık" in html
    assert "İkinci başlık" in html
    assert "Üçüncü başlık" in html


def test_dosya_renders_sepia_dossier():
    html = _render("dosya")
    assert 'class="stage' in html
    assert "ARA ZAM" in html
    assert "Source Serif" in html
    assert 'class="dossier-stamp"' in html
    assert "#f4ecd8" in html  # sepia palette
