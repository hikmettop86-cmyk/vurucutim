from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\n", encoding="utf-8")
    app = create_app(config_dir=cfg, db_path=tmp_path / "db.sqlite",
                     scheduler=False)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_feeds_page_renders_empty(client):
    r = client.get("/feeds")
    assert r.status_code == 200
    assert "RSS Havuzu".encode() in r.data


def test_add_feed_valid(client):
    fixture = (Path(__file__).parent / "fixtures" / "feed_generic.xml").read_bytes()
    with patch("short_bot.web.routes.feeds.fetch_feed_url") as mock_fetch, \
         patch("short_bot.web.routes.feeds.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = fixture
        r = client.post("/feeds/add", data={"url": "https://ornek.com/rss"},
                        follow_redirects=True)
    assert r.status_code == 200
    r2 = client.get("/feeds")
    assert b"ornek.com" in r2.data


def test_add_feed_invalid_url_rejected(client):
    with patch("short_bot.web.routes.feeds.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"<html>not a feed</html>"
        r = client.post("/feeds/add", data={"url": "https://notafeed.com"},
                        follow_redirects=True)
    assert "geçerli bir RSS".encode() in r.data or "gecerli".encode() in r.data
