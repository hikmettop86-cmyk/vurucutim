"""POST /channels/<slug>/test-proxy endpoint tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

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
    return create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates",
        music_root=tmp_path / "music", cache_dir=tmp_path / "cache",
        lock_dir=tmp_path / "locks", logs_dir=tmp_path / "logs",
        output_root=tmp_path / "out",
        secrets_path=tmp_path / "secrets.yaml",
        scheduler=False,
    )


def test_test_proxy_empty_url_returns_400(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    r = client.post("/channels/galatasaray/test-proxy",
                    json={"proxy_url": ""})
    assert r.status_code == 400
    body = r.get_json()
    assert body == {"ok": False, "error": "proxy URL bos"}


def test_test_proxy_success_returns_ip(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"ip": "1.2.3.4"}
    fake_resp.status_code = 200
    fake_resp.text = "Germany"
    fake_session = MagicMock()
    fake_session.get.return_value = fake_resp

    with patch("short_bot.web.routes.youtube.build_proxied_requests_session",
               return_value=fake_session):
        r = client.post("/channels/g/test-proxy",
                        json={"proxy_url": "http://h:1"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["ip"] == "1.2.3.4"


def test_test_proxy_credentials_redacted_in_error(tmp_path):
    """Error message should not leak user:pass even if exception contains it."""
    app = _make_app(tmp_path)
    client = app.test_client()
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception(
        "connection failed for http://alice:s3cret@bad:1080"
    )
    with patch("short_bot.web.routes.youtube.build_proxied_requests_session",
               return_value=fake_session):
        r = client.post("/channels/g/test-proxy",
                        json={"proxy_url": "http://alice:s3cret@bad:1080"})
    body = r.get_json()
    assert body["ok"] is False
    assert "alice" not in body["error"]
    assert "s3cret" not in body["error"]
    assert "***" in body["error"]
