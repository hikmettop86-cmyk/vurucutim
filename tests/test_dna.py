import pytest
from pydantic import ValidationError
from unittest.mock import patch

from short_bot.dna import (
    ARCHETYPES, DnaSpec, DnaPalette, DnaFonts, DnaTone,
    generate_dna, build_dna_prompt,
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
