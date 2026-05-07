import pytest

from short_bot.db import init_db, record_short
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "x.sqlite"
    eng = init_db(db_path)
    record_short(eng, channel="ch1", rss_item_guid="g1", title="Alpha",
                 file_path="output/ch1/a.mp4", duration_s=6, script_json="{}", render_ms=1000)
    record_short(eng, channel="ch2", rss_item_guid="g2", title="Beta",
                 file_path="output/ch2/b.mp4", duration_s=6, script_json="{}", render_ms=1000)
    return create_app(config_dir=cfg_dir, db_path=db_path, scheduler=False)


def test_shorts_list_shows_all(app):
    client = app.test_client()
    resp = client.get("/shorts")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Alpha" in body
    assert "Beta" in body


def test_shorts_filter_by_channel(app):
    client = app.test_client()
    resp = client.get("/shorts/grid?channel=ch1")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Alpha" in body
    assert "Beta" not in body


def test_shorts_search_query(app):
    client = app.test_client()
    resp = client.get("/shorts/grid?q=Alpha")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Alpha" in body
    assert "Beta" not in body


def test_short_detail_view(app):
    client = app.test_client()
    resp = client.get("/shorts/1")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Alpha" in body
    assert "ch1" in body


def test_short_detail_404_when_missing(app):
    client = app.test_client()
    resp = client.get("/shorts/9999")
    assert resp.status_code == 404


def test_shorts_filter_since_today_includes_recent(app):
    """Both seeded shorts use _utcnow() default → should appear under since=today."""
    client = app.test_client()
    body = client.get("/shorts/grid?since=today").data.decode("utf-8")
    assert "Alpha" in body
    assert "Beta" in body


def test_shorts_filter_since_1h_includes_recent(app):
    client = app.test_client()
    body = client.get("/shorts/grid?since=1h").data.decode("utf-8")
    assert "Alpha" in body


def test_shorts_filter_youtube_no_when_none_uploaded(app):
    """No YT uploads seeded → youtube=no should still return all shorts."""
    client = app.test_client()
    body = client.get("/shorts/grid?youtube=no").data.decode("utf-8")
    assert "Alpha" in body
    assert "Beta" in body


def test_shorts_filter_youtube_yes_when_none_uploaded(app):
    """No YT uploads seeded → youtube=yes returns nothing."""
    client = app.test_client()
    body = client.get("/shorts/grid?youtube=yes").data.decode("utf-8")
    assert "Alpha" not in body
    assert "Beta" not in body


def test_shorts_list_shows_active_filter_pill(app):
    client = app.test_client()
    body = client.get("/shorts?since=today").data.decode("utf-8")
    assert "Aktif filtre" in body
    assert "bugün" in body
