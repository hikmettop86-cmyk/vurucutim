from unittest.mock import patch, MagicMock

import pytest

from short_bot.youtube.metadata_writer import (
    YoutubeMetadata, build_metadata_prompt, generate_youtube_metadata,
)


def _channel(language="tr"):
    """Minimal channel-like object — only attrs used by build_metadata_prompt."""
    c = MagicMock()
    c.name = "Son Dakika"
    c.handle = "@son-dakika"
    c.language = language
    c.keywords = ["son dakika", "haber"]
    c.youtube = None
    return c


def _script(header_top="ŞOK GELİŞME", header_bottom="UZAYDA YAŞAM",
            body="Bilim adamları bugün yeni bir gezegenin atmosferinde "
                  "yaşam izleri tespit etti. Bu keşif insanlık tarihinin "
                  "en önemli buluşlarından biri olabilir."):
    return {"header_top": header_top, "header_bottom": header_bottom,
            "body_paragraph": body, "category": "bilim", "mood": "breaking"}


def test_prompt_includes_channel_and_script():
    prompt = build_metadata_prompt(
        channel=_channel(), script=_script(),
        rss_source=None, rss_link=None,
    )
    assert "Son Dakika" in prompt
    assert "ŞOK GELİŞME" in prompt
    assert "@son-dakika" in prompt
    # Language hint
    assert "Türkçe" in prompt or "Turkish" in prompt or "tr" in prompt


def test_prompt_includes_source_when_rss():
    prompt = build_metadata_prompt(
        channel=_channel(), script=_script(),
        rss_source="Reuters", rss_link="https://example.com/x",
    )
    assert "Reuters" in prompt
    assert "https://example.com/x" in prompt
    # Should ask Sonnet to credit source
    assert "kaynak" in prompt.lower() or "source" in prompt.lower()


def test_prompt_marks_generator_mode_when_no_rss():
    prompt = build_metadata_prompt(
        channel=_channel(), script=_script(),
        rss_source=None, rss_link=None,
    )
    # Generator-mode hint — AI-generated original content
    assert "özgün" in prompt.lower() or "original" in prompt.lower() or \
           "AI" in prompt or "yapay zeka" in prompt.lower()


def test_prompt_requires_fair_use_disclaimer():
    prompt = build_metadata_prompt(
        channel=_channel(), script=_script(),
        rss_source="Reuters", rss_link="https://example.com/x",
    )
    # Sonnet must include copyright/fair-use boilerplate
    assert "telif" in prompt.lower() or "fair use" in prompt.lower() or \
           "copyright" in prompt.lower()


def test_prompt_specifies_json_output_schema():
    prompt = build_metadata_prompt(
        channel=_channel(), script=_script(),
        rss_source=None, rss_link=None,
    )
    assert '"title"' in prompt
    assert '"description"' in prompt
    assert '"tags"' in prompt


def test_prompt_specifies_title_max_100_chars():
    prompt = build_metadata_prompt(
        channel=_channel(), script=_script(),
        rss_source=None, rss_link=None,
    )
    assert "100" in prompt  # title length cap mentioned


def test_metadata_pydantic_validates():
    m = YoutubeMetadata(
        title="Bilim adamları yaşam buldu",
        description="Açıklama gövdesi" * 5,
        tags=["bilim", "uzay", "shorts"],
    )
    assert m.title.startswith("Bilim")
    assert "shorts" in m.tags


def test_metadata_pydantic_rejects_too_long_title():
    with pytest.raises(Exception):  # ValidationError
        YoutubeMetadata(
            title="x" * 101, description="ok ok ok", tags=["a"],
        )


def test_metadata_pydantic_caps_tags():
    """Schema accepts 0-20 tags; more should reject."""
    m = YoutubeMetadata(title="ok", description="ok ok ok ok",
                        tags=[f"t{i}" for i in range(20)])
    assert len(m.tags) == 20
    with pytest.raises(Exception):
        YoutubeMetadata(title="ok", description="ok ok ok ok",
                        tags=[f"t{i}" for i in range(21)])


def test_generate_calls_run_json_with_sonnet_default():
    fake_meta = YoutubeMetadata(
        title="Test başlık", description="Açıklama " * 30, tags=["a", "b"],
    )
    with patch("short_bot.youtube.metadata_writer.run_json",
               return_value=fake_meta) as m:
        result = generate_youtube_metadata(
            channel=_channel(), script=_script(),
            rss_source=None, rss_link=None,
            claude_path="claude",
        )
    assert result is fake_meta
    # Default model is sonnet
    assert m.call_args.kwargs["model"] == "sonnet"


def test_generate_passes_explicit_model_override():
    fake_meta = YoutubeMetadata(title="x", description="ok ok ok ok", tags=["a"])
    with patch("short_bot.youtube.metadata_writer.run_json", return_value=fake_meta) as m:
        generate_youtube_metadata(
            channel=_channel(), script=_script(),
            rss_source=None, rss_link=None,
            claude_path="claude", model="haiku",
        )
    assert m.call_args.kwargs["model"] == "haiku"


def test_generate_youtube_metadata_forwards_backend_and_api_key():
    fake_meta = YoutubeMetadata(
        title="Test başlık", description="Açıklama " * 30, tags=["a", "b"],
    )
    with patch("short_bot.youtube.metadata_writer.run_json",
               return_value=fake_meta) as m:
        generate_youtube_metadata(
            channel=_channel(), script=_script(),
            rss_source=None, rss_link=None,
            claude_path="claude", backend="openrouter", api_key="k",
        )
    assert m.call_args.kwargs["backend"] == "openrouter"
    assert m.call_args.kwargs["api_key"] == "k"


def test_prompt_persona_humor_override_ve_base_title():
    # Mizah personalı kanalda metadata haber tonunu EZER + reel'in SEO başlığını temel alır.
    c = _channel()
    c.reel = MagicMock()
    c.reel.persona = "vahsi_mizah"
    prompt = build_metadata_prompt(
        channel=c, script=_script(), rss_source=None, rss_link=None,
        base_title="Elektrikli Yilan: Bataklığın Kabadayısı")
    assert "Elektrikli Yilan: Bataklığın Kabadayısı" in prompt   # base_title temel
    assert "MİZAH" in prompt                                     # mizah override'ı
    assert "EKLEME" in prompt                                    # fair-use disclaimer EKLEME


def test_prompt_persona_yoksa_override_yok():
    # Persona yoksa (haber kanalı) override eklenmez — MagicMock persona non-str → boş.
    prompt = build_metadata_prompt(
        channel=_channel(), script=_script(), rss_source=None, rss_link=None)
    assert "KANAL TONU (EN ÖNEMLİ" not in prompt
