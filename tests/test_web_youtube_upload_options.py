"""Manuel upload rotasi privacy + publish_at opsiyonlarini isler."""
from __future__ import annotations

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
    from short_bot.db import init_db, record_short
    with app.app_context():
        from flask import current_app
        db_path = current_app.config["SHORTBOT_DB_PATH"]
        eng = init_db(db_path)
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"\x00" * 16)
        return record_short(
            eng, channel="ch", rss_item_guid="g1", title="Test Short",
            file_path=str(video_file), duration_s=6,
            script_json='{"header_top": "T"}', render_ms=1000,
        )


def _patches():
    """Ortak mock'lar: kimlik + uploader + metadata (ag yok)."""
    return (
        patch("short_bot.web.routes.youtube.yt_auth.load_credentials",
              return_value=MagicMock()),
        patch("short_bot.web.routes.youtube.upload_video", return_value="VID1"),
        patch("short_bot.web.routes.youtube.generate_youtube_metadata",
              side_effect=Exception()),
    )


def test_privacy_unlisted_passed_to_status(tmp_path):
    app = _make_app(tmp_path)
    short_id = _seed_short(app, tmp_path)
    client = app.test_client()
    p_load, p_up, p_meta = _patches()
    with p_load, p_up as mock_up, p_meta:
        client.post(f"/shorts/{short_id}/upload-youtube",
                    data={"privacy": "unlisted"})
    _, ukw = mock_up.call_args
    assert ukw["status"]["privacyStatus"] == "unlisted"
    assert "publishAt" not in ukw["status"]


def test_invalid_privacy_falls_back_to_channel_default(tmp_path):
    # Kanalda youtube bolumu yok -> varsayilan "public"
    app = _make_app(tmp_path)
    short_id = _seed_short(app, tmp_path)
    client = app.test_client()
    p_load, p_up, p_meta = _patches()
    with p_load, p_up as mock_up, p_meta:
        client.post(f"/shorts/{short_id}/upload-youtube",
                    data={"privacy": "hacker"})
    _, ukw = mock_up.call_args
    assert ukw["status"]["privacyStatus"] == "public"


def test_future_publish_at_sets_publishat_and_private(tmp_path):
    app = _make_app(tmp_path)
    short_id = _seed_short(app, tmp_path)
    client = app.test_client()
    p_load, p_up, p_meta = _patches()
    future = "2099-01-01T10:00:00.000Z"
    with p_load, p_up as mock_up, p_meta:
        client.post(f"/shorts/{short_id}/upload-youtube",
                    data={"privacy": "public", "publish_at": future})
    _, ukw = mock_up.call_args
    assert ukw["status"]["publishAt"] == future
    assert ukw["status"]["privacyStatus"] == "private"


def test_past_publish_at_rejected_no_upload(tmp_path):
    app = _make_app(tmp_path)
    short_id = _seed_short(app, tmp_path)
    client = app.test_client()
    p_load, p_up, p_meta = _patches()
    past = "2000-01-01T10:00:00.000Z"
    with p_load, p_up as mock_up, p_meta:
        r = client.post(f"/shorts/{short_id}/upload-youtube",
                        data={"publish_at": past}, follow_redirects=False)
    mock_up.assert_not_called()
    assert r.status_code in (302, 303)


def test_no_options_uses_channel_default(tmp_path):
    app = _make_app(tmp_path)
    short_id = _seed_short(app, tmp_path)
    client = app.test_client()
    p_load, p_up, p_meta = _patches()
    with p_load, p_up as mock_up, p_meta:
        client.post(f"/shorts/{short_id}/upload-youtube", data={})
    _, ukw = mock_up.call_args
    assert ukw["status"]["privacyStatus"] == "public"
    assert "publishAt" not in ukw["status"]
