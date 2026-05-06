import json
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.config import ChannelConfig, Settings
from short_bot.models import NewsItem, ScoredItem, Script, Highlight, RenderJob
from short_bot.pipeline import run_pipeline


def _silent_log():
    log = logging.getLogger("test.silent")
    log.handlers = []
    log.addHandler(logging.NullHandler())
    return log


def _make_test_channel(*, bg_video=None):
    """Minimal ChannelConfig sufficient for _resolve_pexels_bg."""
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="t", name="T", keywords=["x"],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=5, template="newscast",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@x", output_dir="output/t",
        enabled=True, cta_enabled=False, cta_text="",
        cta_icons=[], cta_duration_s=0, cta_show_handle=False,
        language="tr", bg_video=bg_video,
    )


def _settings():
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude", playwright_browser="chromium",
        web_host="127.0.0.1", web_port=5000,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"dna": "opus", "default": "haiku"},
    )


def _channel(tmp_path):
    return ChannelConfig(
        slug="test", name="T", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=2, min_score=5.0,
        max_candidates_per_run=10, template="default",
        colors={"primary": "#c81e1e", "accent": "#ffea3b", "bg_gradient": ["#1a3b6b", "#0a1a3b"]},
        handle="@x", output_dir=str(tmp_path / "output" / "test"),
        enabled=True, cta_enabled=True, cta_text="A · B · C",
        cta_icons=["❤️", "🔔", "↗️"], cta_duration_s=1, cta_show_handle=True,
        language="tr",
    )


def _script():
    return Script(
        header_top="X", header_bottom="Y", photo_overlay="Z",
        body_paragraph="Türkiye Cumhuriyet Merkez Bankası faizi indirdi. Karar şok yarattı.",
        highlights=[Highlight(text="şok yarattı", color="red")],
        category="EKONOMİ", mood="breaking",
    )


def test_pipeline_happy_path(tmp_path):
    item = NewsItem(guid="g1", title="Faiz indirimi", link="http://x", source="S",
                    pub_date=datetime(2026, 5, 5), thumb_url=None, description="d")
    settings = _settings()
    channel = _channel(tmp_path)
    db_path = tmp_path / "db.sqlite"
    music_root = tmp_path / "music"
    (music_root / "breaking").mkdir(parents=True)
    src_music = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    (music_root / "breaking" / "a.mp3").write_bytes(src_music.read_bytes())

    def fake_compose(frames_dir, music_path, out_path, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"fake mp4 bytes")
        return Path(out_path)

    with patch("short_bot.pipeline.fetch_rss", return_value=[item]), \
         patch("short_bot.pipeline.score_items",
               return_value=[ScoredItem(item=item, score=9.0, reasoning="ok")]), \
         patch("short_bot.pipeline.extract_article", return_value="Tam makale gövdesi"), \
         patch("short_bot.pipeline.write_script", return_value=_script()), \
         patch("short_bot.pipeline.download_and_blur_thumb", return_value=None), \
         patch("short_bot.image_picker.pick_image_for_script", return_value=None), \
         patch("short_bot.pipeline.render_frames", return_value=60), \
         patch("short_bot.pipeline.compose_video", side_effect=fake_compose):
        result = run_pipeline(
            channel=channel, settings=settings,
            db_path=db_path, music_root=music_root,
            templates_dir=Path("templates"), cache_dir=tmp_path / "cache",
            logs_dir=tmp_path / "logs", lock_dir=tmp_path / "locks",
            trigger="cli",
        )

    assert result.status == "success"
    assert result.short_path is not None
    assert result.short_path.exists()
    assert result.short_path.suffix == ".mp4"
    assert "test" in result.short_path.parent.name  # channel slug in path


def test_pipeline_no_candidates(tmp_path):
    settings = _settings()
    channel = _channel(tmp_path)
    db_path = tmp_path / "db.sqlite"

    with patch("short_bot.pipeline.fetch_rss", return_value=[]):
        result = run_pipeline(
            channel=channel, settings=settings,
            db_path=db_path, music_root=tmp_path / "music",
            templates_dir=Path("templates"), cache_dir=tmp_path / "cache",
            logs_dir=tmp_path / "logs", lock_dir=tmp_path / "locks",
            trigger="cli",
        )
    assert result.status == "no_candidates"


def test_pipeline_records_failure_on_render_error(tmp_path):
    item = NewsItem(guid="g1", title="X", link="http://x", source=None,
                    pub_date=None, thumb_url=None, description=None)
    settings = _settings()
    channel = _channel(tmp_path)
    db_path = tmp_path / "db.sqlite"
    music_root = tmp_path / "music"
    (music_root / "breaking").mkdir(parents=True)
    (music_root / "breaking" / "a.mp3").write_bytes(b"fake")

    with patch("short_bot.pipeline.fetch_rss", return_value=[item]), \
         patch("short_bot.pipeline.score_items",
               return_value=[ScoredItem(item=item, score=9.0, reasoning="ok")]), \
         patch("short_bot.pipeline.extract_article", return_value="body"), \
         patch("short_bot.pipeline.write_script", return_value=_script()), \
         patch("short_bot.pipeline.download_and_blur_thumb", return_value=None), \
         patch("short_bot.image_picker.pick_image_for_script", return_value=None), \
         patch("short_bot.pipeline.render_frames", side_effect=RuntimeError("crash")):
        result = run_pipeline(
            channel=channel, settings=settings,
            db_path=db_path, music_root=music_root,
            templates_dir=Path("templates"), cache_dir=tmp_path / "cache",
            logs_dir=tmp_path / "logs", lock_dir=tmp_path / "locks",
            trigger="cli",
        )
    assert result.status == "failed"
    assert "crash" in result.error


def test_pipeline_passes_channel_aware_args(tmp_path):
    item = NewsItem(guid="g1", title="Faiz indirimi", link="http://x", source="S",
                    pub_date=datetime(2026, 5, 5), thumb_url=None, description="d")
    settings = _settings()
    channel = _channel(tmp_path)
    db_path = tmp_path / "db.sqlite"
    music_root = tmp_path / "music"
    (music_root / "breaking").mkdir(parents=True)
    src_music = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    (music_root / "breaking" / "a.mp3").write_bytes(src_music.read_bytes())

    write_script_mock = MagicMock(return_value=_script())

    def fake_compose(frames_dir, music_path, out_path, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"fake mp4 bytes")
        return Path(out_path)

    with patch("short_bot.pipeline.fetch_rss", return_value=[item]), \
         patch("short_bot.pipeline.score_items",
               return_value=[ScoredItem(item=item, score=9.0, reasoning="ok")]), \
         patch("short_bot.pipeline.extract_article", return_value="Tam makale gövdesi"), \
         patch("short_bot.pipeline.write_script", write_script_mock), \
         patch("short_bot.pipeline.download_and_blur_thumb", return_value=None), \
         patch("short_bot.image_picker.pick_image_for_script", return_value=None), \
         patch("short_bot.pipeline.render_frames", return_value=60), \
         patch("short_bot.pipeline.compose_video", side_effect=fake_compose):
        run_pipeline(
            channel=channel, settings=settings,
            db_path=db_path, music_root=music_root,
            templates_dir=Path("templates"), cache_dir=tmp_path / "cache",
            logs_dir=tmp_path / "logs", lock_dir=tmp_path / "locks",
            trigger="cli",
        )

    # write_script must be called with channel= and model="haiku" (from settings.claude_models default)
    assert write_script_mock.called
    _, kwargs = write_script_mock.call_args
    assert kwargs.get("channel") is channel
    assert kwargs.get("model") == "haiku"


def test_pipeline_skips_pexels_when_bg_video_disabled(tmp_path, monkeypatch):
    """When bg_video is None on the channel, Pexels code paths must not be called."""
    from short_bot.pipeline import _resolve_pexels_bg
    ch = _make_test_channel(bg_video=None)
    secrets_path = tmp_path / "secrets.yaml"
    cache = tmp_path / "cache"

    called = {"search": 0, "download": 0}
    monkeypatch.setattr("short_bot.pexels.search_videos",
                        lambda *a, **k: (called.__setitem__("search", called["search"] + 1) or []))
    monkeypatch.setattr("short_bot.pexels.download_video",
                        lambda *a, **k: (called.__setitem__("download", called["download"] + 1) or None))

    out = _resolve_pexels_bg(channel=ch, cache_dir=cache, secrets_path=secrets_path,
                              log=_silent_log())
    assert out is None
    assert called["search"] == 0
    assert called["download"] == 0


def test_pipeline_pexels_fallback_when_no_api_key(tmp_path, monkeypatch):
    from short_bot.pipeline import _resolve_pexels_bg
    from short_bot.config import BgVideoConfig
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    ch = _make_test_channel(bg_video=BgVideoConfig(enabled=True))
    secrets_path = tmp_path / "secrets.yaml"
    out = _resolve_pexels_bg(channel=ch, cache_dir=tmp_path / "cache",
                              secrets_path=secrets_path, log=_silent_log())
    assert out is None


def test_pipeline_pexels_downloads_first_successful_candidate(tmp_path, monkeypatch):
    from short_bot.pipeline import _resolve_pexels_bg
    from short_bot.config import BgVideoConfig
    from short_bot.pexels import PexelsCandidate
    monkeypatch.setenv("PEXELS_API_KEY", "TESTKEY")

    ch = _make_test_channel(bg_video=BgVideoConfig(enabled=True))

    fake_candidates = [
        PexelsCandidate(id=1, url="https://x/a.mp4", duration_s=10),
        PexelsCandidate(id=2, url="https://x/b.mp4", duration_s=12),
    ]
    monkeypatch.setattr("short_bot.pexels.search_videos",
                        lambda *a, **k: fake_candidates)

    cached = tmp_path / "cache" / "pexels_videos" / "abc.mp4"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"video")

    monkeypatch.setattr("short_bot.pexels.download_video",
                        lambda url, cache_dir, **k: cached if "a.mp4" in url else None)

    out = _resolve_pexels_bg(channel=ch, cache_dir=tmp_path / "cache",
                              secrets_path=tmp_path / "secrets.yaml",
                              log=_silent_log())
    assert out == cached


def test_pipeline_pexels_returns_none_when_search_empty(tmp_path, monkeypatch):
    from short_bot.pipeline import _resolve_pexels_bg
    from short_bot.config import BgVideoConfig
    monkeypatch.setenv("PEXELS_API_KEY", "TESTKEY")
    ch = _make_test_channel(bg_video=BgVideoConfig(enabled=True))
    monkeypatch.setattr("short_bot.pexels.search_videos", lambda *a, **k: [])
    out = _resolve_pexels_bg(channel=ch, cache_dir=tmp_path / "cache",
                              secrets_path=tmp_path / "secrets.yaml",
                              log=_silent_log())
    assert out is None
