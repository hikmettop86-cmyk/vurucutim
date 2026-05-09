import pytest
from pydantic import ValidationError
from unittest.mock import patch

from short_bot.dna import (
    ARCHETYPES, DnaSpec, DnaPalette, DnaFonts, DnaTone,
    generate_dna, build_dna_prompt,
    build_css_override, _banner_shape_css, _highlight_css, _chip_css,
)


def test_archetypes_list_has_fifteen():
    # 7 original + 8 news-themed (added 2026-05-08)
    assert len(ARCHETYPES) == 15
    # Original 7
    assert "newscast" in ARCHETYPES
    assert "tabloid" in ARCHETYPES
    assert "magazine" in ARCHETYPES
    assert "kinetic" in ARCHETYPES
    assert "dark-tech" in ARCHETYPES
    assert "stadium" in ARCHETYPES
    assert "meme" in ARCHETYPES
    # News-themed 8
    assert "politika" in ARCHETYPES
    assert "ekonomi" in ARCHETYPES
    assert "spor-haber" in ARCHETYPES
    assert "tech-haber" in ARCHETYPES
    assert "hava-durumu" in ARCHETYPES
    assert "yerel" in ARCHETYPES
    assert "gundem" in ARCHETYPES
    assert "dosya" in ARCHETYPES


def test_palette_validates_hex():
    DnaPalette(primary="#c81e1e", accent="#ffea3b",
               bg_gradient=["#1a3b6b", "#0a1a3b"], body_bg=["#1a1a2a", "#0a0a1a"])
    with pytest.raises(ValidationError):
        DnaPalette(primary="red", accent="#ffea3b",
                   bg_gradient=["#000","#111"], body_bg=["#000","#111"])
    with pytest.raises(ValidationError):
        DnaPalette(primary="#cc", accent="#ffea3b",  # too short
                   bg_gradient=["#000","#111"], body_bg=["#000","#111"])


def test_palette_normalizes_hex_to_lowercase():
    p = DnaPalette(primary="#C81E1E", accent="#FFEA3B",
                   bg_gradient=["#000000","#111111"], body_bg=["#000000","#111111"])
    assert p.primary == "#c81e1e"
    assert p.accent == "#ffea3b"


def test_palette_gradient_must_have_two_entries():
    with pytest.raises(ValidationError):
        DnaPalette(primary="#000000", accent="#ffffff",
                   bg_gradient=["#000000"], body_bg=["#000","#111"])


def test_tone_defaults():
    t = DnaTone(voice="formal", style="concise")
    assert t.sentence_max_words == 18
    assert t.paragraph_sentences == (3, 5)
    assert t.body_max_chars == 350


def test_tone_voice_required():
    with pytest.raises(ValidationError):
        DnaTone(voice="", style="x")


def test_dna_full_validates():
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(headline="Inter", body="Inter"),
        tone=DnaTone(voice="formal", style="concise"),
        category_icon="📰",
        persona_summary="Resmi haber kanalı.",
    )
    assert dna.archetype == "newscast"
    assert dna.banner_shape == "flat"   # default
    assert dna.highlight_style == "bg-flat"
    assert dna.chip_style == "rounded"


def test_dna_archetype_must_be_valid():
    with pytest.raises(ValidationError):
        DnaSpec(
            archetype="random-thing",
            palette=DnaPalette(primary="#000000", accent="#ffffff",
                               bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            persona_summary="x",
        )


def test_dna_banner_shape_validates():
    with pytest.raises(ValidationError):
        DnaSpec(
            archetype="newscast",
            palette=DnaPalette(primary="#000000", accent="#ffffff",
                               bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            persona_summary="x",
            banner_shape="bouncy",  # not in Literal
        )


def test_build_dna_prompt_includes_inputs():
    p = build_dna_prompt(
        name="Spor Şort", keywords=["Bundesliga", "Bayern"],
        language="de", topic_hint="Hardcore taraftar", target_audience="Genç erkek",
    )
    assert "Spor Şort" in p
    assert "Bundesliga" in p
    assert "Deutsch" in p             # LANGUAGE_NAMES[de] resolved
    assert "Hardcore" in p
    assert "Genç erkek" in p


def test_generate_dna_returns_dnaspec():
    fake = DnaSpec(
        archetype="stadium",
        palette=DnaPalette(primary="#0a4d2a", accent="#ffd700",
                           bg_gradient=["#1a8b3a","#0a4d1a"],
                           body_bg=["#0a1a0a","#000000"]),
        fonts=DnaFonts(headline="Bebas Neue", body="Inter",
                       google_imports=["Bebas+Neue"]),
        tone=DnaTone(voice="leidenschaftlich", style="dynamisch", body_max_chars=280),
        banner_shape="slanted", highlight_style="marker", chip_style="pill",
        category_icon="⚽", persona_summary="...",
    )
    with patch("short_bot.dna.run_json", return_value=fake) as m:
        result = generate_dna(name="x", keywords=["y"], language="de",
                              claude_path="claude", model="opus")
    assert result.archetype == "stadium"
    # Verify the model parameter was passed through
    assert m.call_args.kwargs["model"] == "opus"


def test_generate_dna_default_model_is_opus():
    fake = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="z",
    )
    with patch("short_bot.dna.run_json", return_value=fake) as m:
        generate_dna(name="x", keywords=["y"], language="tr")
    assert m.call_args.kwargs["model"] == "opus"


def _sample_dna(**overrides):
    base = dict(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(headline="Bebas Neue", body="Inter",
                       google_imports=["Bebas+Neue", "Inter:wght@400;700;900"]),
        tone=DnaTone(voice="x", style="y"),
        category_icon="📰", persona_summary="x",
    )
    base.update(overrides)
    return DnaSpec(**base)


def test_build_css_includes_google_import():
    css = build_css_override(_sample_dna())
    assert "fonts.googleapis.com" in css
    assert "Bebas+Neue" in css


def test_build_css_includes_root_variables():
    css = build_css_override(_sample_dna())
    assert "--primary: #c81e1e" in css
    assert "--accent: #ffea3b" in css
    assert "--bg-grad-1: #1a3b6b" in css
    assert "--font-headline: 'Bebas Neue'" in css


def test_build_css_no_google_imports_skips_import_line():
    """When chosen fonts are NOT in the auto-import map (system fonts), no @import emitted."""
    dna = _sample_dna(fonts=DnaFonts(headline="Impact", body="Georgia", google_imports=[]))
    css = build_css_override(dna)
    assert "@import" not in css


def test_build_css_auto_imports_recognized_fonts():
    """Picking a font like Bebas Neue auto-adds its Google Fonts import."""
    dna = _sample_dna(fonts=DnaFonts(headline="Bebas Neue", body="Roboto", google_imports=[]))
    css = build_css_override(dna)
    assert "Bebas+Neue" in css
    assert "Roboto" in css
    assert "fonts.googleapis.com" in css


def test_banner_shape_helpers_return_unique_strings():
    flat = _banner_shape_css("flat")
    ribbon = _banner_shape_css("ribbon")
    slanted = _banner_shape_css("slanted")
    sharp = _banner_shape_css("sharp")
    assert len({flat, ribbon, slanted, sharp}) == 4


def test_highlight_styles_return_distinct_css():
    bg = _highlight_css("bg-flat", "#ff0000", "#ffffff")
    underline = _highlight_css("underline", "#ff0000", "#ffffff")
    marker = _highlight_css("marker", "#ff0000", "#ffffff")
    neon = _highlight_css("neon", "#ff0000", "#ffffff")
    assert len({bg, underline, marker, neon}) == 4
    # underline should mention text-decoration
    assert "underline" in underline.lower() or "text-decoration" in underline.lower()


def test_chip_styles_return_distinct_border_radius():
    rounded = _chip_css("rounded")
    sharp = _chip_css("sharp")
    pill = _chip_css("pill")
    assert "border-radius" in rounded
    assert rounded != sharp != pill


def test_dna_custom_css_default_empty():
    """custom_css defaults to empty string when not provided."""
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )
    assert dna.custom_css == ""


def test_dna_custom_css_accepts_value():
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
        custom_css="body { background: url(data:image/svg+xml,...); }",
    )
    assert "background:" in dna.custom_css


def test_build_dna_prompt_includes_custom_css_section():
    p = build_dna_prompt(name="Test", keywords=["x"], language="tr")
    assert "ÖZGÜR CSS" in p
    assert "custom_css" in p


def test_build_dna_prompt_lists_forbidden_css_properties():
    p = build_dna_prompt(name="Test", keywords=["x"], language="tr")
    assert "position" in p
    assert "YASAKLI" in p
    assert ".header" in p
    assert ".body" in p
    assert ".persistent" in p


def test_build_dna_prompt_json_schema_includes_custom_css():
    p = build_dna_prompt(name="Test", keywords=["x"], language="tr")
    assert '"custom_css"' in p


def test_dna_custom_css_max_length_enforced():
    long_css = "/* x */" * 1500   # ~9000 chars, exceeds 8000 limit
    with pytest.raises(ValidationError):
        DnaSpec(
            archetype="newscast",
            palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                               bg_gradient=["#1a3b6b","#0a1a3b"],
                               body_bg=["#1a1a2a","#0a0a1a"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            persona_summary="x",
            custom_css=long_css,
        )


def test_build_css_appends_custom_css_when_present():
    dna = _sample_dna(custom_css="body { background: red; }")
    css = build_css_override(dna)
    assert "/* Channel custom_css (Opus-generated, color-sanitized) */" in css
    assert "body { background: red; }" in css
    # Ordering: custom_css must come AFTER structural rules
    assert css.index("--primary") < css.index("/* Channel custom_css")


def test_dnaspec_animation_style_default_none():
    """Existing DNA without animation_style must default to 'none'."""
    from short_bot.dna import DnaSpec
    spec = DnaSpec.model_validate({
        "archetype": "newscast",
        "palette": {
            "primary": "#bb1f1f", "accent": "#ffd54a",
            "bg_gradient": ["#0a0a0a", "#1a1a1a"],
            "body_bg": ["#101010", "#1f1f1f"],
            "text_main": "#ffffff", "text_muted": "#cccccc",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "x", "style": "x", "forbidden": [],
            "sentence_max_words": 18, "paragraph_sentences": [3, 5],
            "body_max_chars": 350, "headline_style_hint": "",
        },
        "persona_summary": "x", "custom_css": "", "ui_badge": "x",
    })
    assert spec.animation_style == "none"


def test_dnaspec_animation_style_accepts_all_six_values():
    from short_bot.dna import DnaSpec
    base = {
        "archetype": "newscast",
        "palette": {
            "primary": "#bb1f1f", "accent": "#ffd54a",
            "bg_gradient": ["#0a0a0a", "#1a1a1a"],
            "body_bg": ["#101010", "#1f1f1f"],
            "text_main": "#ffffff", "text_muted": "#cccccc",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "x", "style": "x", "forbidden": [],
            "sentence_max_words": 18, "paragraph_sentences": [3, 5],
            "body_max_chars": 350, "headline_style_hint": "",
        },
        "persona_summary": "x", "custom_css": "", "ui_badge": "x",
    }
    for v in ["none", "fade-up", "slide-in", "stagger-reveal",
              "typewriter", "zoom-in"]:
        spec = DnaSpec.model_validate({**base, "animation_style": v})
        assert spec.animation_style == v


def test_dnaspec_animation_style_rejects_invalid():
    import pytest
    from short_bot.dna import DnaSpec
    base = {
        "archetype": "newscast",
        "palette": {
            "primary": "#bb1f1f", "accent": "#ffd54a",
            "bg_gradient": ["#0a0a0a", "#1a1a1a"],
            "body_bg": ["#101010", "#1f1f1f"],
            "text_main": "#ffffff", "text_muted": "#cccccc",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "x", "style": "x", "forbidden": [],
            "sentence_max_words": 18, "paragraph_sentences": [3, 5],
            "body_max_chars": 350, "headline_style_hint": "",
        },
        "persona_summary": "x", "custom_css": "", "ui_badge": "x",
        "animation_style": "rainbow-explosion",
    }
    with pytest.raises(Exception):  # pydantic ValidationError
        DnaSpec.model_validate(base)


def test_build_css_omits_custom_css_section_when_empty():
    dna = _sample_dna(custom_css="")
    css = build_css_override(dna)
    assert "Channel custom_css" not in css


def test_build_css_appends_readability_safety_net_after_custom_css():
    """Even if Opus injects gradient-text trick into custom_css, the safety net
    appended LAST forces .header .top/.bot back to solid fill."""
    nasty_css = (
        ".header .top { -webkit-text-fill-color: transparent; "
        "background-clip: text; -webkit-text-stroke: 2px black; }"
    )
    dna = _sample_dna(custom_css=nasty_css)
    css = build_css_override(dna)
    # safety net exists
    assert "Readability safety net" in css
    assert "-webkit-text-fill-color: currentColor !important" in css
    # and is positioned AFTER the custom_css block
    assert css.index("Channel custom_css") < css.index("Readability safety net")


def test_palette_header_color_overrides_default_empty():
    p = DnaPalette(primary="#c81e1e", accent="#ffea3b",
                    bg_gradient=["#000000", "#111111"], body_bg=["#000000", "#111111"])
    assert p.header_top_color == ""
    assert p.header_bottom_color == ""


def test_palette_header_color_overrides_accept_hex():
    p = DnaPalette(primary="#c81e1e", accent="#ffea3b",
                    bg_gradient=["#000000", "#111111"], body_bg=["#000000", "#111111"],
                    header_top_color="#ff00aa", header_bottom_color="#00ffff")
    assert p.header_top_color == "#ff00aa"
    assert p.header_bottom_color == "#00ffff"


def test_palette_header_color_rejects_invalid_hex():
    with pytest.raises(ValidationError):
        DnaPalette(primary="#c81e1e", accent="#ffea3b",
                    bg_gradient=["#000000", "#111111"], body_bg=["#000000", "#111111"],
                    header_top_color="red")


def test_build_css_omits_header_color_when_empty():
    dna = _sample_dna()
    css = build_css_override(dna)
    assert ".header .top { color:" not in css
    assert ".header .bot { color:" not in css


def test_build_css_emits_header_color_when_set():
    dna = _sample_dna()
    dna.palette.header_top_color = "#ff00aa"
    dna.palette.header_bottom_color = "#00ffff"
    css = build_css_override(dna)
    assert ".header .top { color: #ff00aa !important; }" in css
    assert ".header .bot { color: #00ffff !important; }" in css


def test_build_dna_prompt_includes_readability_rules():
    p = build_dna_prompt(name="Test", keywords=["x"], language="tr")
    assert "OKUNABILIRLIK" in p
    # explicit ban on gradient text trick
    assert "-webkit-text-fill-color: transparent" in p
    # element shadow limit
    assert "MAKS 2" in p


def test_dna_ui_badge_default_empty():
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )
    assert dna.ui_badge == ""


def test_dna_ui_badge_max_length_enforced():
    with pytest.raises(ValidationError):
        DnaSpec(
            archetype="newscast",
            palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                               bg_gradient=["#1a3b6b","#0a1a3b"],
                               body_bg=["#1a1a2a","#0a0a1a"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            persona_summary="x",
            ui_badge="x" * 25,
        )


def test_build_dna_prompt_includes_ui_badge_section():
    p = build_dna_prompt(name="Test", keywords=["x"], language="tr")
    assert "UI_BADGE" in p
    assert '"ui_badge"' in p
    assert "SON DAKİKA" in p   # explicit warning against haber default for non-haber channels


def test_build_css_omits_custom_css_section_when_whitespace_only():
    dna = _sample_dna(custom_css="   \n\n  ")
    css = build_css_override(dna)
    assert "Channel custom_css" not in css


def test_generate_dna_for_video_uses_article_context(monkeypatch):
    """The per-video prompt must include headline + body excerpt."""
    from short_bot.config import ChannelConfig
    from short_bot.dna import build_dna_for_video_prompt

    cfg = ChannelConfig(
        slug="spor-haber", name="Spor", keywords=["futbol"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@spor", output_dir="out",
        enabled=True, cta_enabled=True, cta_text="x", cta_icons=[],
        cta_duration_s=4, cta_show_handle=True, language="tr",
        max_age_hours=24, dynamic_dna=True,
    )
    prompt = build_dna_for_video_prompt(
        channel=cfg,
        headline="Galatasaray Osimhen transferinde son aşamada",
        body="Sarı kırmızılılar Napoli'den Osimhen için 75M Euro teklifte bulundu...",
    )
    assert "Osimhen" in prompt
    assert "Galatasaray" in prompt
    assert "Sarı kırmızılılar" in prompt
    # Channel persona should be referenced when channel has DNA
    assert "Spor" in prompt or "futbol" in prompt
