"""Verify run_pipeline routes by channel.content_source."""
from unittest.mock import patch

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
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=None, script_model=None,
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
