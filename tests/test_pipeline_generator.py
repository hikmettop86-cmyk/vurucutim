# tests/test_pipeline_generator.py
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.config import ChannelConfig, GeneratorConfig, Settings
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.generator import GeneratorResult, GeneratorRetryExhausted
from short_bot.pipeline import run_pipeline


def _settings():
    return Settings(ffmpeg_path="ffmpeg", claude_cli_path="claude",
                    playwright_browser="chromium", web_host="127.0.0.1",
                    web_port=5005, fuzzy_dedup_threshold=0.85,
                    log_level="INFO",
                    claude_models={"dna": "opus", "default": "haiku"})


def _dna_spec():
    return DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="duygusal", style="kısa",
                     forbidden=[], sentence_max_words=12,
                     body_max_chars=200, headline_style_hint="iki satır"),
        category_icon="❤️",
        persona_summary="Sevgi sözleri.",
    )


def _gen_channel(tmp_path, slug="sevgi"):
    return ChannelConfig(
        slug=slug, name="Sevgi", keywords=[], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=0.0,
        max_candidates_per_run=1, template="kinetic",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir=str(tmp_path / "out"),
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=_dna_spec(), script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(
            topic="Sevgi sözleri üret",
            forbidden_lookback=10, max_retries=2, fuzzy_threshold=0.85,
        ),
    )


def _ok_result(text="Aşk anlayışta başlar.", tag="tanisma"):
    return GeneratorResult(
        text=text,
        topic_tag=tag,
        script={
            "header_top": "AŞK", "header_bottom": "ÜZERİNE",
            "photo_overlay": "Sevgi",
            "body_paragraph": f"{text} Bu söz sevdayı anlatır.",
            "highlights": [], "category": "ask", "mood": "neutral",
        },
        image_keywords=["couple silhouette", "sunset"],
    )


def test_generator_pipeline_success(tmp_path):
    cfg = _gen_channel(tmp_path)
    logs = tmp_path / "logs"; logs.mkdir()
    out_path = tmp_path / "out" / "video.mp4"

    with patch("short_bot.pipeline.generate_quote", return_value=_ok_result()), \
         patch("short_bot.pipeline.pick_image_for_generator", return_value=None), \
         patch("short_bot.pipeline.pick_music",
               return_value=Path("dummy.mp3")), \
         patch("short_bot.pipeline.render_frames"), \
         patch("short_bot.pipeline.compose_video") as compose:
        # Make compose write a fake mp4 file at the expected path
        def _write_fake_mp4(frames_dir, music, op, **kw):
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"fake mp4")
        compose.side_effect = _write_fake_mp4

        result = run_pipeline(
            channel=cfg, settings=_settings(),
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path, templates_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks", logs_dir=logs, trigger="test",
        )

    assert result.status == "success"
    assert result.short_path is not None and result.short_path.exists()


def test_generator_retry_exhaustion_marks_run_failed(tmp_path):
    """All max_retries return duplicates → GeneratorRetryExhausted → run failed."""
    cfg = _gen_channel(tmp_path)
    logs = tmp_path / "logs"; logs.mkdir()

    # Pre-seed DB with the text so layer-1 hash collision triggers each time
    from short_bot.db import init_db
    from short_bot.generated_db import insert_generated
    eng = init_db(tmp_path / "db.sqlite")
    fixed = _ok_result("Tekrarlı söz.")
    insert_generated(eng, channel="sevgi", text=fixed.text,
                     topic_tag=fixed.topic_tag, language="tr",
                     status="used", short_id=None)
    eng.dispose()

    with patch("short_bot.pipeline.generate_quote", return_value=fixed):
        result = run_pipeline(
            channel=cfg, settings=_settings(),
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path, templates_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks", logs_dir=logs, trigger="test",
        )

    assert result.status == "failed"
    assert "duplicate" in (result.error or "").lower() \
           or "exhausted" in (result.error or "").lower()


def test_generator_records_used_status_and_short_id(tmp_path):
    """After successful render, generated_items.short_id is populated."""
    cfg = _gen_channel(tmp_path)
    logs = tmp_path / "logs"; logs.mkdir()

    with patch("short_bot.pipeline.generate_quote", return_value=_ok_result()), \
         patch("short_bot.pipeline.pick_image_for_generator", return_value=None), \
         patch("short_bot.pipeline.pick_music",
               return_value=Path("dummy.mp3")), \
         patch("short_bot.pipeline.render_frames"), \
         patch("short_bot.pipeline.compose_video") as compose:
        def _w(frames_dir, music, op, **kw):
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"fake")
        compose.side_effect = _w

        run_pipeline(
            channel=cfg, settings=_settings(),
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path, templates_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks", logs_dir=logs, trigger="test",
        )

    # Verify DB state
    from short_bot.db import init_db
    from short_bot.generated_db import generated_items
    from sqlalchemy import select
    eng = init_db(tmp_path / "db.sqlite")
    with eng.connect() as conn:
        rows = conn.execute(select(generated_items)).fetchall()
    eng.dispose()
    assert len(rows) == 1
    assert rows[0].status == "used"
    assert rows[0].short_id is not None


def test_generator_pipeline_passes_bg_video_path_to_composer(monkeypatch, tmp_path):
    """When the generator-mode channel has bg_video enabled and a Pexels key is
    present, _run_generator must call compose_video with bg_video_path set."""
    from short_bot.config import BgVideoConfig
    from short_bot.pexels import PexelsCandidate

    # Set Pexels env so resolve_pexels_api_key returns it
    monkeypatch.setenv("PEXELS_API_KEY", "K")

    # Mock Pexels search/download
    fake_bg = tmp_path / "fake_bg.mp4"
    fake_bg.write_bytes(b"x")
    monkeypatch.setattr("short_bot.pexels.search_videos",
                        lambda *a, **k: [PexelsCandidate(id=1, url="https://x/a.mp4", duration_s=5)])
    monkeypatch.setattr("short_bot.pexels.download_video",
                        lambda url, cache_dir, **k: fake_bg)

    # Capture compose_video kwargs
    captured: dict = {}

    def fake_compose(frames, music, out, **kw):
        captured.update(kw)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-mp4")

    monkeypatch.setattr("short_bot.pipeline.compose_video", fake_compose)

    # Build a channel with bg_video enabled
    cfg = _gen_channel(tmp_path)
    cfg = ChannelConfig(
        **{**cfg.__dict__, "bg_video": BgVideoConfig(enabled=True, scale=0.80)}
    )
    logs = tmp_path / "logs"
    logs.mkdir()

    with patch("short_bot.pipeline.generate_quote", return_value=_ok_result()), \
         patch("short_bot.pipeline.pick_image_for_generator", return_value=None), \
         patch("short_bot.pipeline.pick_music", return_value=Path("dummy.mp3")), \
         patch("short_bot.pipeline.render_frames"):
        result = run_pipeline(
            channel=cfg, settings=_settings(),
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path, templates_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks", logs_dir=logs, trigger="test",
        )

    assert result.status == "success"
    assert captured.get("bg_video_path") == fake_bg
    assert captured.get("fg_scale") == 0.80


def test_generator_pipeline_legacy_when_bg_video_disabled(monkeypatch, tmp_path):
    """Without bg_video on the channel, compose_video receives bg_video_path=None
    and fg_scale=1.0 (legacy fullscreen layout)."""
    captured: dict = {}

    def fake_compose(frames, music, out, **kw):
        captured.update(kw)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-mp4")

    monkeypatch.setattr("short_bot.pipeline.compose_video", fake_compose)

    # Channel with no bg_video (default None)
    cfg = _gen_channel(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()

    with patch("short_bot.pipeline.generate_quote", return_value=_ok_result()), \
         patch("short_bot.pipeline.pick_image_for_generator", return_value=None), \
         patch("short_bot.pipeline.pick_music", return_value=Path("dummy.mp3")), \
         patch("short_bot.pipeline.render_frames"):
        result = run_pipeline(
            channel=cfg, settings=_settings(),
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path, templates_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks", logs_dir=logs, trigger="test",
        )

    assert result.status == "success"
    assert captured.get("bg_video_path") is None
    assert captured.get("fg_scale", 1.0) == 1.0
