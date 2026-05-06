import json
from unittest.mock import patch
from short_bot.web import create_app


def _make_app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "ch.yaml").write_text(
        "slug: ch\nname: C\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: '* * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
        "handle: '@ch'\noutput_dir: out\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    return create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates",
        music_root=tmp_path / "music", cache_dir=tmp_path / "cache",
        lock_dir=tmp_path / "locks", logs_dir=tmp_path / "logs",
        output_root=tmp_path / "out", scheduler=False,
    )


def test_refresh_route_invokes_orchestrator(tmp_path):
    app = _make_app(tmp_path)
    from short_bot.youtube.stats_refresh import RefreshResult
    with patch("short_bot.web.routes.youtube_stats.refresh_channel_stats",
                return_value=RefreshResult("ch", video_count=2,
                                            channel_updated=True)) as m:
        client = app.test_client()
        resp = client.post("/channels/ch/youtube/refresh-stats",
                            follow_redirects=False)
    assert resp.status_code == 302
    m.assert_called_once()


def test_refresh_route_404_on_missing_channel(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    resp = client.post("/channels/nonexistent/youtube/refresh-stats")
    assert resp.status_code == 404
