import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

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


def test_connect_redirects_to_google_when_secrets_present(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "client_secrets.json").write_text(json.dumps({
        "web": {
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://127.0.0.1:5005/oauth/callback"],
        }
    }))
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    client = app.test_client()
    resp = client.post("/channels/ch/youtube/connect", follow_redirects=False)
    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers["Location"]


def test_connect_flashes_error_when_secrets_missing(tmp_path):
    app = _make_app(tmp_path)
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    client = app.test_client()
    resp = client.post("/channels/ch/youtube/connect", follow_redirects=False)
    assert resp.status_code == 302
    assert "/channels/ch/edit" in resp.headers["Location"]


def test_connect_404_when_channel_missing(tmp_path):
    app = _make_app(tmp_path)
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    client = app.test_client()
    resp = client.post("/channels/nonexistent/youtube/connect",
                       follow_redirects=False)
    assert resp.status_code == 404


def test_callback_exchanges_code_and_saves_token(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "client_secrets.json").write_text(json.dumps({
        "web": {
            "client_id": "x.apps.googleusercontent.com", "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://127.0.0.1:5005/oauth/callback"],
        }}))
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    client = app.test_client()

    fake_creds = MagicMock()
    fake_creds.to_json.return_value = '{"token":"abc","scopes":["x"]}'
    fake_info = {"id": "UC9", "snippet": {"title": "T"},
                  "statistics": {"subscriberCount": "1", "videoCount": "1"}}

    with patch("short_bot.youtube.auth.Flow.from_client_secrets_file") as mflow_cls:
        flow = MagicMock()
        flow.credentials = fake_creds
        mflow_cls.return_value = flow
        with patch("short_bot.web.routes.youtube.yt_auth.fetch_and_save_channel_info",
                   return_value=fake_info) as mfetch:
            resp = client.get("/oauth/callback?code=fakecode&state=ch",
                              follow_redirects=False)

    assert resp.status_code == 302
    assert "/channels/ch/edit" in resp.headers["Location"]
    flow.fetch_token.assert_called_once_with(code="fakecode")
    assert (yt_root / "ch" / "token.json").exists()
    mfetch.assert_called_once()


def test_callback_404_on_unknown_state(tmp_path):
    app = _make_app(tmp_path)
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    client = app.test_client()
    resp = client.get("/oauth/callback?code=x&state=missing",
                      follow_redirects=False)
    assert resp.status_code == 404


def test_disconnect_removes_token(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text("{}")
    (yt_root / "ch" / "channel_info.json").write_text("{}")
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    client = app.test_client()
    resp = client.post("/channels/ch/youtube/disconnect",
                       follow_redirects=False)
    assert resp.status_code == 302
    assert not (yt_root / "ch" / "token.json").exists()
    assert (yt_root / "ch" / "channel_info.json").exists()


def test_disconnect_404_when_channel_missing(tmp_path):
    app = _make_app(tmp_path)
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    client = app.test_client()
    resp = client.post("/channels/nonexistent/youtube/disconnect",
                       follow_redirects=False)
    assert resp.status_code == 404


def test_upload_route_calls_uploader_and_records_db(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text(json.dumps({
        "token": "x", "refresh_token": "y", "client_id": "x",
        "client_secret": "y", "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }))
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root

    out_dir = tmp_path / "out" / "ch"
    out_dir.mkdir(parents=True)
    mp4 = out_dir / "v.mp4"
    mp4.write_bytes(b"\x00")

    from short_bot.db import init_db, record_short
    eng = init_db(app.config["SHORTBOT_DB_PATH"])
    sid = record_short(eng, channel="ch", rss_item_guid="g1",
                        title="T", file_path=str(mp4), duration_s=6,
                        script_json='{"header_top":"A","header_bottom":"B",'
                                     '"photo_overlay":"X","body_paragraph":"yyyyyyyyyyyyyyyyyyyy",'
                                     '"highlights":[],"category":"x","mood":"neutral"}',
                        render_ms=1)

    with patch("short_bot.youtube.auth.Credentials") as MockCreds, \
         patch("short_bot.web.routes.youtube.upload_video", return_value="VID") as mup:
        mock_cred = MagicMock(); mock_cred.expired = False
        MockCreds.from_authorized_user_info.return_value = mock_cred
        client = app.test_client()
        resp = client.post(f"/shorts/{sid}/upload-youtube",
                           follow_redirects=False)
    assert resp.status_code == 302
    mup.assert_called_once()
    from short_bot.db import get_youtube_upload_for_short
    row = get_youtube_upload_for_short(eng, short_id=sid)
    assert row.status == "success"
    assert row.video_id == "VID"


def test_upload_route_404_when_short_missing(tmp_path):
    app = _make_app(tmp_path)
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    client = app.test_client()
    resp = client.post("/shorts/9999/upload-youtube")
    assert resp.status_code == 404


def test_upload_route_flashes_error_when_not_connected(tmp_path):
    app = _make_app(tmp_path)
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    out_dir = tmp_path / "out" / "ch"; out_dir.mkdir(parents=True)
    mp4 = out_dir / "v.mp4"; mp4.write_bytes(b"\x00")
    from short_bot.db import init_db, record_short
    eng = init_db(app.config["SHORTBOT_DB_PATH"])
    sid = record_short(eng, channel="ch", rss_item_guid="g",
                        title="T", file_path=str(mp4), duration_s=6,
                        script_json='{"header_top":"A","header_bottom":"B",'
                                     '"photo_overlay":"X","body_paragraph":"yyyyyyyyyyyyyyyyyyyy",'
                                     '"highlights":[],"category":"x","mood":"neutral"}',
                        render_ms=1)
    client = app.test_client()
    resp = client.post(f"/shorts/{sid}/upload-youtube",
                       follow_redirects=False)
    assert resp.status_code == 302
    from short_bot.db import get_youtube_upload_for_short
    assert get_youtube_upload_for_short(eng, short_id=sid) is None


def test_upload_secrets_saves_valid_json(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    client = app.test_client()

    payload = json.dumps({
        "web": {
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://127.0.0.1:5005/oauth/callback"],
        }
    }).encode("utf-8")

    from io import BytesIO
    resp = client.post(
        "/channels/ch/youtube/upload-secrets",
        data={"client_secrets": (BytesIO(payload), "client_secrets.json")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    saved = (yt_root / "ch" / "client_secrets.json").read_text(encoding="utf-8")
    assert "client_id" in saved


def test_upload_secrets_rejects_invalid_json(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    client = app.test_client()
    from io import BytesIO
    resp = client.post(
        "/channels/ch/youtube/upload-secrets",
        data={"client_secrets": (BytesIO(b"not json"), "x.json")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    # Redirect with flash error, no file written
    assert resp.status_code == 302
    assert not (yt_root / "ch" / "client_secrets.json").exists()


def test_upload_secrets_rejects_missing_oauth_keys(tmp_path):
    """JSON valid but missing 'web' or 'installed' key — not an OAuth client."""
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    client = app.test_client()
    from io import BytesIO
    bad = json.dumps({"random": "thing"}).encode("utf-8")
    resp = client.post(
        "/channels/ch/youtube/upload-secrets",
        data={"client_secrets": (BytesIO(bad), "x.json")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert not (yt_root / "ch" / "client_secrets.json").exists()


def test_upload_secrets_404_when_channel_missing(tmp_path):
    app = _make_app(tmp_path)
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    client = app.test_client()
    from io import BytesIO
    resp = client.post(
        "/channels/nonexistent/youtube/upload-secrets",
        data={"client_secrets": (BytesIO(b"{}"), "x.json")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 404


def test_reset_removes_all_files(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text("{}")
    (yt_root / "ch" / "channel_info.json").write_text("{}")
    (yt_root / "ch" / "client_secrets.json").write_text("{}")
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    client = app.test_client()
    resp = client.post("/channels/ch/youtube/reset", follow_redirects=False)
    assert resp.status_code == 302
    assert not (yt_root / "ch").exists()


def test_reset_404_when_channel_missing(tmp_path):
    app = _make_app(tmp_path)
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    client = app.test_client()
    resp = client.post("/channels/nonexistent/youtube/reset")
    assert resp.status_code == 404


def test_upload_route_uses_sonnet_metadata_when_available(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text(json.dumps({
        "token": "x", "refresh_token": "y", "client_id": "x",
        "client_secret": "y", "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }))
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    out_dir = tmp_path / "out" / "ch"; out_dir.mkdir(parents=True)
    mp4 = out_dir / "v.mp4"; mp4.write_bytes(b"\x00")

    from short_bot.db import init_db, record_short
    eng = init_db(app.config["SHORTBOT_DB_PATH"])
    sid = record_short(eng, channel="ch", rss_item_guid="g1",
                        title="T", file_path=str(mp4), duration_s=6,
                        script_json='{"header_top":"A","header_bottom":"B",'
                                     '"photo_overlay":"X","body_paragraph":"yyyyyyyyyyyyyyyyyyyy",'
                                     '"highlights":[],"category":"x","mood":"neutral"}',
                        render_ms=1)

    from short_bot.youtube.metadata_writer import YoutubeMetadata
    fake_meta = YoutubeMetadata(
        title="Sonnet üretti bunu",
        description="Sonnet'in zengin açıklaması — kaynak vs telif",
        tags=["sonnet", "ai", "shorts"],
    )

    with patch("short_bot.youtube.auth.Credentials") as MockCreds, \
         patch("short_bot.web.routes.youtube.upload_video", return_value="VID") as mup, \
         patch("short_bot.web.routes.youtube.generate_youtube_metadata",
               return_value=fake_meta) as mmeta:
        mock_cred = MagicMock(); mock_cred.expired = False
        MockCreds.from_authorized_user_info.return_value = mock_cred
        client = app.test_client()
        resp = client.post(f"/shorts/{sid}/upload-youtube", follow_redirects=False)
    assert resp.status_code == 302
    mmeta.assert_called_once()
    # Snippet built with generated metadata
    sent_snippet = mup.call_args.kwargs["snippet"]
    assert sent_snippet["title"] == "Sonnet üretti bunu"
    assert "zengin açıklaması" in sent_snippet["description"]
    assert "sonnet" in sent_snippet["tags"]


def test_upload_route_falls_back_when_sonnet_fails(tmp_path):
    """Sonnet errors must NOT kill the upload — fall back to bare header concat."""
    app = _make_app(tmp_path)
    yt_root = tmp_path / "yt_creds"
    (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text(json.dumps({
        "token": "x", "refresh_token": "y", "client_id": "x",
        "client_secret": "y", "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }))
    app.config["SHORTBOT_YT_CREDS_DIR"] = yt_root
    out_dir = tmp_path / "out" / "ch"; out_dir.mkdir(parents=True)
    mp4 = out_dir / "v.mp4"; mp4.write_bytes(b"\x00")
    from short_bot.db import init_db, record_short
    eng = init_db(app.config["SHORTBOT_DB_PATH"])
    sid = record_short(eng, channel="ch", rss_item_guid="g1",
                        title="T", file_path=str(mp4), duration_s=6,
                        script_json='{"header_top":"A","header_bottom":"B",'
                                     '"photo_overlay":"X","body_paragraph":"yyyyyyyyyyyyyyyyyyyy",'
                                     '"highlights":[],"category":"x","mood":"neutral"}',
                        render_ms=1)

    with patch("short_bot.youtube.auth.Credentials") as MockCreds, \
         patch("short_bot.web.routes.youtube.upload_video", return_value="VID") as mup, \
         patch("short_bot.web.routes.youtube.generate_youtube_metadata",
               side_effect=RuntimeError("sonnet down")):
        mock_cred = MagicMock(); mock_cred.expired = False
        MockCreds.from_authorized_user_info.return_value = mock_cred
        client = app.test_client()
        resp = client.post(f"/shorts/{sid}/upload-youtube", follow_redirects=False)
    assert resp.status_code == 302
    sent_snippet = mup.call_args.kwargs["snippet"]
    # Fallback uses header_top | header_bottom
    assert sent_snippet["title"] == "A | B"
    assert "#shorts" in sent_snippet["description"]
