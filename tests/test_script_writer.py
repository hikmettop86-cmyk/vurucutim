from unittest.mock import patch
from datetime import datetime

import pytest

from short_bot.models import NewsItem, Script
from short_bot.script_writer import write_script, build_script_prompt, ARCHETYPE_PROMPTS, build_script_prompt_for_channel
from short_bot.config import ChannelConfig
from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone


def _item():
    return NewsItem(guid="g", title="Faiz indirimi", link="http://x", source="Reuters",
                    pub_date=datetime(2026, 5, 5), thumb_url=None,
                    description="Karar şok yarattı.")


def _channel(language="tr", template="newscast", dna=None):
    return ChannelConfig(
        slug="test", name="T", keywords=["x"],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 * * * *", duration_s=30, min_score=8.0,
        max_candidates_per_run=10, template=template,
        colors={"primary": "#c81e1e", "accent": "#ffea3b",
                "bg_gradient": ["#1a3b6b", "#0a1a3b"]},
        handle="@x", output_dir="output/test",
        enabled=True, cta_enabled=False, cta_text="",
        cta_icons=[], cta_duration_s=0, cta_show_handle=False,
        language=language, dna=dna,
    )


def test_build_script_prompt_includes_body_and_title():
    p = build_script_prompt(_item(), "Tam makale gövdesi metni")
    assert "Faiz indirimi" in p
    assert "Tam makale gövdesi metni" in p
    assert "header_top" in p
    assert "highlights" in p


def test_write_script_returns_script_model():
    fake = Script(
        header_top="FAİZ ŞOKU",
        header_bottom="BAŞLADI",
        photo_overlay="250 BAZ PUAN İNDİRİM",
        body_paragraph="Türkiye Cumhuriyet Merkez Bankası faizi 250 baz puan indirdi. Karar piyasada şok yarattı.",
        highlights=[{"text": "250 baz puan", "color": "yellow"}],
        category="EKONOMİ",
        mood="breaking",
    )
    with patch("short_bot.script_writer.run_json", return_value=fake):
        result = write_script(_item(), "Tam makale", claude_path="claude")
    assert isinstance(result, Script)
    assert result.header_top == "FAİZ ŞOKU"


def test_archetype_prompts_cover_four_active():
    """2026-05-19: cut from 7 → 3 (newscast + stadium + stat-hero).
    2026-05-20: added bigquote (fullscreen attributed quotation)."""
    expected = {"newscast", "stadium", "stat-hero", "bigquote"}
    assert set(ARCHETYPE_PROMPTS.keys()) == expected


def test_build_script_prompt_includes_archetype_instructions():
    item = _item()
    p = build_script_prompt_for_channel(item, "body text", _channel(template="stadium"))
    assert "stadium" in p.lower()
    # Stadium signature word from prompt
    assert "score" in p.lower() or "sports" in p.lower()


def test_build_script_prompt_includes_language_name():
    p = build_script_prompt_for_channel(_item(), "body", _channel(language="de"))
    assert "Deutsch" in p


def test_build_script_prompt_includes_tone_block_when_dna_present():
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"], body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="formal, data-driven", style="concise",
                     forbidden=["clickbait"], sentence_max_words=12,
                     paragraph_sentences=(3, 4), body_max_chars=300),
        persona_summary="x",
    )
    p = build_script_prompt_for_channel(_item(), "body", _channel(dna=dna))
    assert "formal, data-driven" in p
    assert "clickbait" in p
    assert "12" in p   # sentence_max_words


def test_build_script_prompt_no_tone_block_when_no_dna():
    p = build_script_prompt_for_channel(_item(), "body", _channel(dna=None))
    # No tone-block heading should be present
    assert "TONE OF VOICE" not in p


def test_build_script_prompt_states_header_char_limits():
    """Channel-aware prompt must declare hard char limits matching Pydantic max_length."""
    p = build_script_prompt_for_channel(_item(), "body", _channel())
    assert "header_top: MAX 25" in p
    assert "header_bottom: MAX 35" in p


def test_build_script_prompt_tr_states_header_char_limits():
    """Legacy Turkish prompt must declare the same hard char limits."""
    p = build_script_prompt(_item(), "body")
    assert "MAX 25 karakter" in p
    assert "MAX 35 karakter" in p


def test_script_header_top_max_25():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Script(
            header_top="X" * 26,
            header_bottom="Y",
            photo_overlay="Z",
            body_paragraph="Yeterince uzun bir paragraf metni icin asgari kosul.",
            highlights=[], category="X", mood="neutral",
        )


def test_script_header_bottom_max_35():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Script(
            header_top="X",
            header_bottom="Y" * 36,
            photo_overlay="Z",
            body_paragraph="Yeterince uzun bir paragraf metni icin asgari kosul.",
            highlights=[], category="X", mood="neutral",
        )
