"""nfl-gameday designed arketibinin config-driven kaydı + render smoke."""
import json
from pathlib import Path

from short_bot.dna import ARCHETYPES, ARCHETYPE_DEFAULTS, DnaSpec, _DESIGNED_ARCHETYPES
from short_bot.pexels import ARCHETYPE_BG_QUERIES
from short_bot.templates_config import ARCHETYPE_OVERFLOW_FIELDS

SLUG = "nfl-gameday"


def test_entry_present_in_archetypes_json():
    entries = json.loads(
        Path("config/archetypes.json").read_text(encoding="utf-8")
    )
    match = [e for e in entries if e["slug"] == SLUG]
    assert len(match) == 1, "nfl-gameday entry tam olarak bir kez olmalı"
    e = match[0]
    d = e["defaults"]
    assert d["colors"]["primary"] and d["colors"]["accent"]
    assert d["colors"]["primary_light"] and len(d["colors"]["bg_gradient"]) == 2
    assert len(d["body_bg"]) == 2
    assert d["text_main"] and d["text_muted"]
    assert d["font_headline"] == "Anton" and d["font_body"] == "Inter"
    assert len(e["pexels_queries"]) >= 3


def test_registered_in_dna():
    assert SLUG in ARCHETYPES
    assert SLUG in {a["slug"] for a in _DESIGNED_ARCHETYPES}
    defaults = ARCHETYPE_DEFAULTS[SLUG]
    assert defaults["primary"] == "#013369"
    assert defaults["accent"] == "#D50A0A"


def test_dnaspec_accepts_nfl_gameday():
    from short_bot.dna import DnaPalette, DnaFonts, DnaTone
    dna = DnaSpec(
        archetype=SLUG,
        palette=DnaPalette(primary="#013369", accent="#D50A0A",
                           bg_gradient=["#0a1f3c", "#04101f"],
                           body_bg=["#0a1f3c", "#04101f"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="dinamik", style="kısa"),
        persona_summary="NFL gameday test kanalı",
    )
    assert dna.archetype == SLUG


def test_pexels_queries_registered():
    pool = ARCHETYPE_BG_QUERIES[SLUG]
    assert any("football" in q.lower() for q in pool)


def test_overflow_fields_standard_selectors():
    fields = ARCHETYPE_OVERFLOW_FIELDS[SLUG]
    selectors = {f.selector for f in fields}
    assert ".header .top" in selectors
    assert ".body-text" in selectors


def test_template_exists_and_has_standard_selectors():
    """nfl-gameday.html.j2 var ve zorunlu standart selector'ları + öğeleri içerir."""
    from pathlib import Path
    template_path = Path("templates/nfl-gameday.html.j2")
    assert template_path.exists()
    html_text = template_path.read_text(encoding="utf-8")
    for needle in (
        'class="top"', 'class="bot"', 'class="yellow"', 'class="body-text"',
        'class="progress"', 'class="handle"', "dna_css", "_auto_fit.js.j2",
        "1080px", "1920px",
    ):
        assert needle in html_text, f"template '{needle}' içermeli"


def test_template_jinja_valid():
    """Jinja2 template parse edilebilir (syntax hatası yok)."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(loader=FileSystemLoader("templates"),
                      autoescape=select_autoescape(["html"]))
    env.get_template("nfl-gameday.html.j2")  # parse — hata fırlatmamalı


def test_nfl_gameday_renders():
    """Gerçek Playwright render smoke (chromium yoksa skip)."""
    import pytest
    playwright = pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    from short_bot.config import Settings
    from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
    from short_bot.dna_smoke import smoke_render_dna

    # chromium binary yoksa skip
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
        palette=DnaPalette(primary="#013369", accent="#D50A0A",
                           bg_gradient=["#0a1f3c", "#04101f"],
                           body_bg=["#0a1f3c", "#04101f"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="dinamik", style="kısa"),
        persona_summary="NFL gameday test kanalı",
    )
    templates = Path(__file__).resolve().parents[1] / "templates"
    ok, reason = smoke_render_dna(
        dna, channel_template=SLUG,
        templates_dir=templates, settings=settings,
        language="tr",
    )
    assert ok, f"expected pass, got: {reason}"


def test_body_has_graceful_clamp_safety_net():
    """Uzun NFL body metni taşmasın diye stadium-pattern güvenlik ağı şart:
    .body-text line-clamp:9 + mask fade + overflow:hidden (taşma kesilir).
    Bu eksikse uzun içerik fotoğraf bandına / progress bara taşar (text-fit bug,
    2026-06-19 düzeltmesi). Auto-fit min'e inse bile graceful kesim kalmalı."""
    html = Path("templates/nfl-gameday.html.j2").read_text(encoding="utf-8")
    assert "-webkit-line-clamp: 9" in html, "body-text line-clamp güvenlik ağı kayıp"
    assert "mask-image" in html, "body-text mask fade kayıp"
    assert "overflow: hidden" in html, "taşma kesimi (overflow:hidden) kayıp"


def test_nfl_gameday_has_special_prompt():
    """nfl-gameday generic değil, NFL-spesifik özel prompt almalı."""
    from short_bot.script_writer import ARCHETYPE_PROMPTS
    prompt = ARCHETYPE_PROMPTS["nfl-gameday"]
    low = prompt.lower()
    assert "touchdown" in low
    assert "nfl" in low
    # generic designed prompt "visual style:" kalıbı içerir; özel prompt içermez
    assert "visual style:" not in low
