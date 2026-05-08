"""Manual upload route uses configured proxy."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_app(tmp_path):
    from short_bot.web import create_app
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
        output_root=tmp_path / "out",
        secrets_path=tmp_path / "secrets.yaml",
        scheduler=False,
    )


def _seed_short(app, tmp_path):
    """Insert a short row into the test DB for upload."""
    from short_bot.db import init_db, record_short
    with app.app_context():
        from flask import current_app
        db_path = current_app.config["SHORTBOT_DB_PATH"]
        eng = init_db(db_path)
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 16)
        return record_short(
            eng,
            channel="ch",
            rss_item_guid="g1",
            title="Test Short",
            file_path=str(video_file),
            duration_s=6,
            script_json='{"header_top": "T"}',
            render_ms=1000,
        )


def test_manual_upload_passes_proxy_http_when_configured(tmp_path):
    app = _make_app(tmp_path)
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text("channel_proxies:\n  ch: http://h:1\n", encoding="utf-8")
    short_id = _seed_short(app, tmp_path)
    client = app.test_client()

    fake_creds = MagicMock()
    with patch("short_bot.web.routes.youtube.yt_auth.load_credentials",
               return_value=fake_creds) as mock_load, \
         patch("short_bot.web.routes.youtube.upload_video",
               return_value="VID123") as mock_upload, \
         patch("short_bot.web.routes.youtube.generate_youtube_metadata",
               side_effect=Exception()), \
         patch("short_bot.web.routes.youtube.build_proxied_http",
               return_value="PROXIED_HTTP") as mock_bph:
        client.post(f"/shorts/{short_id}/upload-youtube")

    # Proxy session passed to load_credentials
    _, kw = mock_load.call_args
    assert "proxy_session" in kw
    assert kw["proxy_session"] is not None
    # http=PROXIED_HTTP passed to upload_video
    _, ukw = mock_upload.call_args
    assert ukw.get("http") == "PROXIED_HTTP"


def test_manual_upload_no_proxy_no_kwargs(tmp_path):
    """When no proxy configured, http=None and proxy_session=None."""
    app = _make_app(tmp_path)
    short_id = _seed_short(app, tmp_path)
    client = app.test_client()

    fake_creds = MagicMock()
    with patch("short_bot.web.routes.youtube.yt_auth.load_credentials",
               return_value=fake_creds) as mock_load, \
         patch("short_bot.web.routes.youtube.upload_video",
               return_value="VID999") as mock_upload, \
         patch("short_bot.web.routes.youtube.generate_youtube_metadata",
               side_effect=Exception()):
        client.post(f"/shorts/{short_id}/upload-youtube")

    # proxy_session=None passed
    _, kw = mock_load.call_args
    assert kw.get("proxy_session") is None
    # http=None
    _, ukw = mock_upload.call_args
    assert ukw.get("http") is None
