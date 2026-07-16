"""Tests for the stat-hero archetype (Phase-1 compositional addition)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from short_bot.dna import ARCHETYPES, ARCHETYPE_DEFAULTS
from short_bot.models import Script, RenderJob
from short_bot.pexels import ARCHETYPE_BG_QUERIES
from short_bot.renderer import build_html
from short_bot.script_writer import ARCHETYPE_PROMPTS
from short_bot.templates_config import ARCHETYPE_OVERFLOW_FIELDS


# --- Registration checks ---------------------------------------------------

def test_stat_hero_in_archetypes_list():
    assert "stat-hero" in ARCHETYPES


def test_stat_hero_has_dna_defaults():
    d = ARCHETYPE_DEFAULTS.get("stat-hero")
    assert d is not None
    for key in ("primary", "accent", "bg_grad_1", "bg_grad_2",
                "text_main", "font_headline", "font_body"):
        assert key in d, f"missing {key}"


def test_stat_hero_has_script_writer_prompt():
    p = ARCHETYPE_PROMPTS.get("stat-hero")
    assert p is not None
    assert "stat" in p.lower() or "rakam" in p.lower() or "sayı" in p.lower()


def test_stat_hero_has_overflow_config():
    cfg = ARCHETYPE_OVERFLOW_FIELDS.get("stat-hero")
    assert cfg is not None
    names = {f.name for f in cfg}
    assert "header_top" in names
    assert "body_paragraph" in names


def test_stat_hero_has_pexels_bg_queries():
    q = ARCHETYPE_BG_QUERIES.get("stat-hero")
    assert q is not None
    assert len(q) >= 2


def test_stat_hero_template_file_exists():
    p = Path("templates/stat-hero.html.j2")
    assert p.exists()


# --- Render integration tests ---------------------------------------------

def _job(body: str, *, headline_top="STAT", headline_bot="2026") -> RenderJob:
    script = Script(
        header_top=headline_top, header_bottom=headline_bot,
        photo_overlay="X", body_paragraph=body, highlights=[],
        category="EKONOMİ", mood="neutral",
    )
    return RenderJob(
        script=script, bg_image_path=None, music_path=Path("dummy.mp3"),
        channel_colors={"primary": "#06b6d4", "accent": "#facc15",
                         "bg_gradient": ["#0f172a", "#020617"]},
        handle="@x", duration_s=6, language="tr",
 rss_source=None,
    )


def _render_and_measure(job: RenderJob) -> dict:
    html = build_html(job, Path("templates/stat-hero.html.j2"))
    td = Path(tempfile.mkdtemp())
    p = td / "x.html"
    p.write_text(html, encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(f"file:///{p.as_posix()}")
        page.wait_for_function("typeof window.__autoFitDone !== 'undefined'")
        page.wait_for_timeout(400)
        try:
            return page.evaluate("""() => {
                const s = document.getElementById('statNumber');
                const c = document.getElementById('statCaption');
                return {
                    stat_number: s ? s.innerText : null,
                    caption: c ? c.innerText : null,
                    body_height: document.querySelector('.body').clientHeight,
                    fallback: s ? s.classList.contains('is-fallback') : null,
                };
            }""")
        finally:
            b.close()


def test_render_extracts_percent_with_comma():
    """%54,3 oran açıklandı → number=%54,3, caption=remainder."""
    m = _render_and_measure(_job(
        "%54,3 oran açıklandı; bütçe gelirleri rekor seviyede."
    ))
    assert m["stat_number"] == "%54,3"
    assert "rekor" in m["caption"]
    assert m["fallback"] is False


def test_render_extracts_yuzde_form():
    """'yüzde 25' form → %25."""
    m = _render_and_measure(_job(
        "yüzde 25 oran arttı; ekonomik göstergeler şu açıdan değişti."
    ))
    assert m["stat_number"] == "%25"


def test_render_extracts_currency():
    """'₺250 milyon' → preserved as-is."""
    m = _render_and_measure(_job(
        "Hazine ₺250 milyon ihraç etti; yatırımcı talebi rekor seviyede."
    ))
    assert "₺" in m["stat_number"]
    assert "250" in m["stat_number"]


def test_render_extracts_large_plain_number():
    """1500 → preserved."""
    m = _render_and_measure(_job(
        "1500 yeni iş açıldı; istihdam artışı sürdürülebilir bir seyirde."
    ))
    assert "1500" in m["stat_number"] or "1.500" in m["stat_number"]


def test_render_fallback_when_no_number():
    """Body without any number → fallback dash + full caption."""
    m = _render_and_measure(_job(
        "Bakan açıklamasında ekonomik istikrarın korunduğunu vurguladı bugün."
    ))
    assert m["fallback"] is True
    # Original text should still be visible in caption
    assert "Bakan" in m["caption"]
