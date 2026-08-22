"""fenerbahce-stadium designed arketibinin config-driven kaydı + template + render."""
import json
from pathlib import Path

from short_bot.dna import ARCHETYPES, ARCHETYPE_DEFAULTS, DnaSpec, _DESIGNED_ARCHETYPES
from short_bot.pexels import ARCHETYPE_BG_QUERIES

SLUG = "fenerbahce-stadium"


def test_entry_present_in_archetypes_json():
    entries = json.loads(Path("config/archetypes.json").read_text(encoding="utf-8"))
    match = [e for e in entries if e["slug"] == SLUG]
    assert len(match) == 1, "fenerbahce-stadium entry tam olarak bir kez olmalı"
    e = match[0]
    d = e["defaults"]
    assert d["colors"]["primary"] == "#002C5F"
    assert d["colors"]["accent"] == "#FFED00"
    assert d["colors"]["primary_light"] and len(d["colors"]["bg_gradient"]) == 2
    assert len(d["body_bg"]) == 2
    assert d["text_main"] and d["text_muted"]
    assert d["font_headline"] == "Anton" and d["font_body"] == "Inter"
    assert len(e["pexels_queries"]) >= 3


def test_registered_in_dna():
    assert SLUG in ARCHETYPES
    assert SLUG in {a["slug"] for a in _DESIGNED_ARCHETYPES}
    defaults = ARCHETYPE_DEFAULTS[SLUG]
    assert defaults["primary"] == "#002C5F"
    assert defaults["accent"] == "#FFED00"


def test_dnaspec_accepts_fenerbahce_stadium():
    from short_bot.dna import DnaPalette, DnaFonts, DnaTone
    dna = DnaSpec(
        archetype=SLUG,
        palette=DnaPalette(primary="#002C5F", accent="#FFED00",
                           bg_gradient=["#0a1430", "#04081a"],
                           body_bg=["#FFED00", "#002C5F"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="dinamik", style="kısa"),
        persona_summary="Fenerbahçe stadium test kanalı",
    )
    assert dna.archetype == SLUG


def test_pexels_queries_registered():
    pool = ARCHETYPE_BG_QUERIES[SLUG]
    assert any("stadium" in q.lower() or "fans" in q.lower() for q in pool)


def test_template_is_balanced_normal_stadium_based():
    """fenerbahce-stadium normal `stadium` teması tabanlı (dengeli) — galatasaray-stadium
    klonu DEĞİL. GS-stadium'a özgü izler (CİMBOM, tribune şeridi, bordo) yok; dengeli
    yapı (flex gövde, grow-max sınırı, geniş alt boşluk, line-clamp) ve standart
    selector iskeleti mevcut. Renkler DNA/config'ten gelir (hardcoded FB rengi yok)."""
    html = Path("templates/fenerbahce-stadium.html.j2").read_text(encoding="utf-8")
    # galatasaray-stadium klonu izleri OLMAMALI (normal stadium tabanına geçildi)
    assert "CİMBOM" not in html, "GS sloganı (CİMBOM) sızmış"
    assert "#A90432" not in html, "GS bordo rengi sızmış"
    assert 'class="tribune"' not in html, "GS-stadium'a özgü tribün şeridi sızmış"
    assert "GS Stadium" not in html, "GS başlığı kalmış"
    # Dengeli normal-stadium yapısı + FB taşma fix'leri (2026-06-20)
    assert "flex: 1" in html, "esnek gövde yok (451px boşluk riski)"
    assert "data-fit-grow-max" in html, "grow dizgini yok (font 80px'e şişer)"
    assert "margin-bottom: 110px" in html, "geniş alt boşluk yok (progress/handle çakışır)"
    assert "-webkit-line-clamp" in html, "graceful clamp güvenlik ağı yok"
    # standart selector iskeleti + zorunlu öğeler
    for needle in (
        'class="top"', 'class="bot"', 'class="yellow"', 'class="body-text"',
        'class="progress"', 'class="handle"', "dna_css", "_auto_fit.js.j2",
        "1080px", "1920px",
    ):
        assert needle in html, f"template '{needle}' içermeli"


def test_template_jinja_valid():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(loader=FileSystemLoader("templates"),
                      autoescape=select_autoescape(["html"]))
    env.get_template("fenerbahce-stadium.html.j2")


def test_fenerbahce_stadium_renders():
    """Gerçek Playwright render smoke (chromium yoksa skip)."""
    import pytest
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    from short_bot.config import Settings
    from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
    from short_bot.dna_smoke import smoke_render_dna
    try:
        with sync_playwright() as p:
            try:
                p.chromium.launch().close()
            except Exception as e:
                pytest.skip(f"chromium not installed: {e}")
    except Exception as e:
        pytest.skip(f"playwright unavailable: {e}")
    settings = Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1",
        web_port=5005, fuzzy_dedup_threshold=0.85,
        log_level="INFO", claude_models={"dna": "opus", "default": "haiku"},
    )
    dna = DnaSpec(
        archetype=SLUG,
        palette=DnaPalette(primary="#002C5F", accent="#FFED00",
                           bg_gradient=["#0a1430", "#04081a"],
                           body_bg=["#FFED00", "#002C5F"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="dinamik", style="kısa"),
        persona_summary="Fenerbahçe stadium test kanalı",
    )
    templates = Path(__file__).resolve().parents[1] / "templates"
    ok, reason = smoke_render_dna(dna, channel_template=SLUG, templates_dir=templates,
                                  settings=settings, language="tr")
    assert ok, f"expected pass, got: {reason}"
