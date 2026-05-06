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
