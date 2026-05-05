"""Tests for the DNA smoke-render helper.

These tests use Playwright + chromium. They are skipped if Playwright
isn't installed or the browser binary is missing.
"""
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

from short_bot.config import Settings
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.dna_smoke import smoke_render_dna


def _settings():
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1",
        web_port=5005, fuzzy_dedup_threshold=0.85,
        log_level="INFO", claude_models={"dna": "opus", "default": "haiku"},
    )


def _dna(custom_css: str = "") -> DnaSpec:
    return DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
        custom_css=custom_css,
    )


def _ensure_chromium():
    """Skip the test if chromium binary is not installed."""
    try:
        with sync_playwright() as p:
            try:
                p.chromium.launch().close()
            except Exception as e:
                pytest.skip(f"chromium not installed: {e}")
    except Exception as e:
        pytest.skip(f"playwright unavailable: {e}")


def test_smoke_render_passes_for_default_dna():
    _ensure_chromium()
    templates = Path(__file__).resolve().parents[1] / "templates"
    ok, reason = smoke_render_dna(
        _dna(), channel_template="newscast",
        templates_dir=templates, settings=_settings(),
        language="tr",
    )
    assert ok, f"expected pass, got: {reason}"


def test_smoke_render_passes_with_decorative_custom_css():
    _ensure_chromium()
    templates = Path(__file__).resolve().parents[1] / "templates"
    css = """
    body::before {
      content: '';
      position: absolute; inset: 0;
      background: radial-gradient(circle at 30% 30%, rgba(255,255,255,.1), transparent 70%);
      pointer-events: none;
    }
    """
    ok, reason = smoke_render_dna(
        _dna(custom_css=css), channel_template="newscast",
        templates_dir=templates, settings=_settings(),
        language="tr",
    )
    assert ok, f"expected pass with decorative CSS, got: {reason}"


def test_smoke_render_fails_when_custom_css_blacks_out_layout():
    _ensure_chromium()
    templates = Path(__file__).resolve().parents[1] / "templates"
    # CSS that paints the entire stage solid black — pixel stddev should be ~0
    css = """
    .stage::after {
      content: '';
      position: absolute; inset: 0;
      background: #000000;
      z-index: 99;
    }
    """
    ok, reason = smoke_render_dna(
        _dna(custom_css=css), channel_template="newscast",
        templates_dir=templates, settings=_settings(),
        language="tr",
    )
    assert not ok
    assert "blank" in reason.lower() or "stddev" in reason.lower()
