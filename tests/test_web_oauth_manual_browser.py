"""OAuth manual-browser flow: connect renders HTML, code_verifier file-based."""
from __future__ import annotations

import json
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


def test_connect_renders_html_with_auth_url(tmp_path):
    """POST /connect should render HTML with auth_url, NOT redirect."""
    app = _make_app(tmp_path)
    yt_root = tmp_path / "data" / "youtube_credentials"
    (yt_root / "ch").mkdir(parents=True)
    # Minimal valid client_secrets.json
    (yt_root / "ch" / "client_secrets.json").write_text(json.dumps({
        "web": {
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:5005/oauth/callback"],
        },
    }), encoding="utf-8")

    with app.test_client() as client:
        with patch("short_bot.web.routes.youtube._yt_root", return_value=yt_root):
            r = client.post("/channels/ch/youtube/connect", follow_redirects=False)

    # Should be 200 OK with HTML, NOT redirect (302)
    assert r.status_code == 200
    body = r.data.decode()
    assert "auth-url" in body
    assert "btn-copy" in body
    assert "https://accounts.google.com" in body  # auth URL embedded

    # code_verifier should be saved to file (not session)
    # db_path = tmp_path / "x.sqlite", so db_path.parent = tmp_path
    pending_file = tmp_path / "oauth_pending" / "ch.json"
    assert pending_file.exists()
    data = json.loads(pending_file.read_text(encoding="utf-8"))
    # "code_verifier" key must be present (value may be None when PKCE not used)
    assert "code_verifier" in data


def test_status_endpoint_returns_connected_false_initially(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "data" / "youtube_credentials"
    yt_root.mkdir(parents=True)

    with app.test_client() as client:
        with patch("short_bot.web.routes.youtube._yt_root", return_value=yt_root):
            r = client.get("/channels/ch/youtube/status")
    assert r.status_code == 200
    assert r.get_json() == {"connected": False}


def test_status_endpoint_returns_true_when_token_exists(tmp_path):
    app = _make_app(tmp_path)
    yt_root = tmp_path / "data" / "youtube_credentials"
    (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text("{}", encoding="utf-8")

    with app.test_client() as client:
        with patch("short_bot.web.routes.youtube._yt_root", return_value=yt_root):
            r = client.get("/channels/ch/youtube/status")
    assert r.status_code == 200
    assert r.get_json() == {"connected": True}
