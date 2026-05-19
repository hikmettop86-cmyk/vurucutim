"""Verify dna.py registers all 15 archetype names."""
import re

from short_bot.dna import ARCHETYPES, DnaSpec, build_dna_prompt


NEW_ARCHETYPES = [
    "politika", "ekonomi", "spor-haber", "tech-haber",
    "hava-durumu", "yerel", "gundem", "dosya",
]


def test_archetypes_list_contains_new_8():
    for name in NEW_ARCHETYPES:
        assert name in ARCHETYPES, f"{name} missing from ARCHETYPES list"
    # 7 original + 8 news-themed + 1 stat-hero (compositional Phase-1, 2026-05-16)
    assert len(ARCHETYPES) == 16


def test_dnaspec_literal_accepts_new_archetypes():
    """Build a minimal DnaSpec with each new archetype."""
    from short_bot.dna import DnaPalette, DnaFonts, DnaTone
    for name in NEW_ARCHETYPES:
        spec = DnaSpec(
            archetype=name,
            palette=DnaPalette(
                primary="#000000", accent="#ffffff",
                bg_gradient=["#000000", "#111111"],
                body_bg=["#000000", "#111111"],
            ),
            fonts=DnaFonts(),
            tone=DnaTone(voice="neutral", style="concise"),
            persona_summary="test",
        )
        assert spec.archetype == name


def test_build_dna_prompt_mentions_new_archetypes():
    prompt = build_dna_prompt(
        name="Test", keywords=["politics"], language="tr",
    )
    for name in NEW_ARCHETYPES:
        assert name in prompt, f"{name} missing from DNA prompt"


def test_build_dna_prompt_has_gundem_format_instruction():
    prompt = build_dna_prompt(name="Test", keywords=[], language="tr")
    # Must instruct LLM about the gundem body format
    assert "gundem" in prompt
    assert "1." in prompt and ("\n" in prompt or "newline" in prompt.lower() or "satırbaşı" in prompt.lower())


def test_build_dna_prompt_has_hava_durumu_field_instruction():
    prompt = build_dna_prompt(name="Test", keywords=[], language="tr")
    assert "hava-durumu" in prompt
    assert "sıcaklık" in prompt or "temperature" in prompt.lower()
