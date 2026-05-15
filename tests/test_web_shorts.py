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


# ---- Bulk delete + count endpoints -----------------------------------------

def test_shorts_count_returns_total_when_no_filter(app):
    """GET /shorts/count?(empty) → 2 (Alpha + Beta seeded)."""
    client = app.test_client()
    r = client.get("/shorts/count")
    assert r.status_code == 200
    assert r.get_json() == {"count": 2}


def test_shorts_count_honors_channel_filter(app):
    client = app.test_client()
    r = client.get("/shorts/count?channel=ch1")
    assert r.get_json() == {"count": 1}


def test_shorts_count_search_query(app):
    client = app.test_client()
    r = client.get("/shorts/count?q=Alpha")
    assert r.get_json() == {"count": 1}


def test_shorts_delete_all_no_filter_clears_everything(app):
    """POST /shorts/delete-all with empty form → all shorts soft-deleted."""
    client = app.test_client()
    r = client.post("/shorts/delete-all", data={}, follow_redirects=False)
    assert r.status_code == 302
    # Re-fetch list: empty
    body = client.get("/shorts").data.decode("utf-8")
    assert "Alpha" not in body
    assert "Beta" not in body


def test_shorts_delete_all_honors_channel_filter(app):
    """POST /shorts/delete-all?channel=ch1 → only Alpha is gone, Beta remains."""
    client = app.test_client()
    client.post("/shorts/delete-all", data={"channel": "ch1"},
                follow_redirects=False)
    body = client.get("/shorts").data.decode("utf-8")
    assert "Alpha" not in body
    assert "Beta" in body


def test_shorts_delete_all_htmx_returns_redirect_header(app):
    client = app.test_client()
    r = client.post("/shorts/delete-all", data={},
                     headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers.get("HX-Redirect") == "/shorts"


def test_shorts_list_shows_bulk_delete_button(app):
    """The 'Tümünü sil' button must appear in the list view."""
    client = app.test_client()
    body = client.get("/shorts").data.decode("utf-8")
    assert "Tümünü sil" in body
    assert '/shorts/delete-all' in body
