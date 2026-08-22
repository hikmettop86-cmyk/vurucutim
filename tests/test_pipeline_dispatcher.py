"""Verify run_pipeline routes by channel.content_source."""
from pathlib import Path
from unittest.mock import patch

import short_bot.pipeline as _pipeline_mod
from short_bot.pipeline import run_pipeline


def test_rss_channel_routes_to_rss_runner(tmp_path):
    """A channel with content_source='rss' calls _run_rss, not _run_generator."""
    from short_bot.config import ChannelConfig
    cfg = ChannelConfig(
        slug="t", name="T", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=6.0,
        max_candidates_per_run=1, template="newscast",
        colors={"primary": "#000", "accent": "#111", "bg_gradient": ["#000", "#111"]},
        handle="@t", output_dir=str(tmp_path / "out"),
        enabled=True,        language="tr", dna=None, script_model=None,
        content_source="rss", generator=None,
    )
    from short_bot.config import Settings
    s = Settings(ffmpeg_path="ffmpeg", claude_cli_path="claude",
                 playwright_browser="chromium", web_host="127.0.0.1",
                 web_port=5005, fuzzy_dedup_threshold=0.85,
                 log_level="INFO", claude_models={"dna": "opus", "default": "haiku"})
    logs = tmp_path / "logs"; logs.mkdir()
    with patch("short_bot.pipeline._run_rss") as rss, \
         patch("short_bot.pipeline._run_generator") as gen:
        rss.return_value = None
        run_pipeline(channel=cfg, settings=s, db_path=tmp_path / "db.sqlite",
                     music_root=tmp_path, templates_dir=tmp_path,
                     cache_dir=tmp_path, lock_dir=tmp_path / "locks",
                     logs_dir=logs, trigger="test")
    assert rss.called
    assert not gen.called


def test_pipeline_resolves_ai_call_with_expected_roles(tmp_path):
    """The generator pipeline must drive its AI calls through resolve_ai_call,
    asking for the 'default' role (generate_quote) and the 'dna' role (DNA
    resolution). This pins the Task 7 backend-routing integration point."""
    from short_bot.config import ChannelConfig, GeneratorConfig, Settings
    from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
    from short_bot.generator import GeneratorResult

    dna = DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="duygusal", style="kısa", forbidden=[],
                     sentence_max_words=12, body_max_chars=200,
                     headline_style_hint="iki satır"),
        category_icon="❤️", persona_summary="Sevgi sözleri.",
    )
    cfg = ChannelConfig(
        slug="sevgi", name="Sevgi", keywords=[], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=0.0,
        max_candidates_per_run=1, template="stat-hero",
        colors={"primary": "#000", "accent": "#fff", "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir=str(tmp_path / "out"),
        enabled=True, language="tr",
        dna=dna, script_model="sonnet", content_source="generator",
        generator=GeneratorConfig(topic="Sevgi sözleri üret",
                                  forbidden_lookback=10, max_retries=2,
                                  fuzzy_threshold=0.85),
    )
    s = Settings(ffmpeg_path="ffmpeg", claude_cli_path="claude",
                 playwright_browser="chromium", web_host="127.0.0.1",
                 web_port=5005, fuzzy_dedup_threshold=0.85,
                 log_level="INFO", claude_models={"dna": "opus", "default": "sonnet"})
    logs = tmp_path / "logs"; logs.mkdir()

    result = GeneratorResult(
        text="Aşk anlayışta başlar.", topic_tag="tanisma",
        script={"header_top": "AŞK", "header_bottom": "ÜZERİNE",
                "photo_overlay": "Sevgi",
                "body_paragraph": "Aşk anlayışta başlar. Bu söz sevdayı anlatır.",
                "highlights": [], "category": "ask", "mood": "neutral"},
        image_keywords=["couple silhouette", "sunset"],
    )

    roles_seen: list[str] = []
    real_resolve = _pipeline_mod.resolve_ai_call

    def spy_resolve(settings, secrets, role):
        roles_seen.append(role)
        return real_resolve(settings, secrets, role)

    def _write_fake_mp4(frames_dir, music, op, **kw):
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_bytes(b"fake mp4")

    with patch("short_bot.pipeline.resolve_ai_call", side_effect=spy_resolve), \
         patch("short_bot.pipeline.generate_quote", return_value=result), \
         patch("short_bot.pipeline.pick_image_for_generator", return_value=None), \
         patch("short_bot.pipeline.pick_music", return_value=Path("dummy.mp3")), \
         patch("short_bot.pipeline.render_frames"), \
         patch("short_bot.pipeline.compose_video", side_effect=_write_fake_mp4):
        run_pipeline(channel=cfg, settings=s, db_path=tmp_path / "db.sqlite",
                     music_root=tmp_path, templates_dir=tmp_path,
                     cache_dir=tmp_path / "cache", lock_dir=tmp_path / "locks",
                     logs_dir=logs, trigger="test")

    # generate_quote → 'default'; DNA resolution → 'dna'
    assert "default" in roles_seen
    assert "dna" in roles_seen


def test_resolve_ai_call_supports_vision_role():
    from short_bot.config import resolve_ai_call, Settings
    s = Settings(
        ffmpeg_path="f", claude_cli_path="claude", playwright_browser="chromium",
        web_host="h", web_port=1, fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"default": "haiku", "vision": "default"},
        ai_backend="openrouter",
        openrouter_models={"default": "x", "vision": "google/gemma-4-31b-it"},
    )
    call = resolve_ai_call(s, {"openrouter_api_key": "k"}, "vision")
    assert call.model == "google/gemma-4-31b-it"
