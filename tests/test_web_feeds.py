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


def test_feed_items_lists_news(client):
    fixture = (Path(__file__).parent / "fixtures" / "feed_generic.xml").read_bytes()
    with patch("short_bot.web.routes.feeds.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = fixture
        client.post("/feeds/add", data={"url": "https://ornek.com/rss"})
    from short_bot.db import init_db, list_feeds
    eng = init_db(client.application.config["SHORTBOT_DB_PATH"])
    fid = list_feeds(eng)[0].id
    with patch("short_bot.web.routes.feeds.fetch_feed_url") as mock_fetch, \
         patch("short_bot.web.routes.feeds.extract_og_image_url", return_value=None):
        from short_bot.models import NewsItem
        from datetime import datetime, timezone
        mock_fetch.return_value = [
            NewsItem(guid="g1", title="Icardi flaş", link="https://o.com/1",
                     source="Örnek", pub_date=datetime.now(timezone.utc),
                     thumb_url=None, description="özet"),
        ]
        r = client.get(f"/feeds/{fid}/items")
    assert r.status_code == 200
    assert "Icardi".encode() in r.data


def test_produce_launches_pipeline_with_item(client):
    cfg_dir = client.application.config["SHORTBOT_CONFIG_DIR"]
    (cfg_dir / "channels" / "testch.yaml").write_text(
        "slug: testch\nname: Test\nkeywords: [test]\n"
        "schedule_cron: '0 * * * *'\nduration_s: 6\nmin_score: 5\n"
        "max_candidates_per_run: 5\ntemplate: newscast\n"
        "colors: {primary: '#fff', accent: '#000', bg_gradient: ['#111','#222']}\n"
        "handle: '@t'\noutput_dir: out\n", encoding="utf-8")

    captured = {}
    def _fake_launch(**kwargs):
        captured.update(kwargs)
    with patch("short_bot.web.routes.feeds.launch_pipeline", _fake_launch):
        r = client.post("/feeds/items/produce", data={
            "guid": "g1", "title": "Icardi flaş", "link": "https://o.com/1",
            "source": "Örnek", "thumb_url": "", "description": "özet",
            "channel_slug": "testch",
        }, follow_redirects=True)
    assert r.status_code == 200
    assert captured.get("trigger") == "manual_feed"
    item = captured.get("preselected_item")
    assert item is not None and item.guid == "g1"
    assert item.title == "Icardi flaş"
    assert captured["channel"].slug == "testch"


def test_produce_unknown_channel_404(client):
    r = client.post("/feeds/items/produce", data={
        "guid": "g1", "title": "T", "link": "https://o.com/1",
        "channel_slug": "yokboyle",
    })
    assert r.status_code == 404
