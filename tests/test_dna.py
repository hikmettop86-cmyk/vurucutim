import pytest
from pydantic import ValidationError
from unittest.mock import patch

from short_bot.dna import (
    ARCHETYPES, DnaSpec, DnaPalette, DnaFonts, DnaTone,
    generate_dna, build_dna_prompt,
    build_css_override, _banner_shape_css, _highlight_css, _chip_css,
)


def test_archetypes_list_has_seven():
    assert len(ARCHETYPES) == 7
    assert "newscast" in ARCHETYPES
    assert "tabloid" in ARCHETYPES
    assert "magazine" in ARCHETYPES
    assert "kinetic" in ARCHETYPES
    assert "dark-tech" in ARCHETYPES
    assert "stadium" in ARCHETYPES
    assert "meme" in ARCHETYPES


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
