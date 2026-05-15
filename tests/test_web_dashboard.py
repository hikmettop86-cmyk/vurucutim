import pytest
from datetime import datetime, timedelta

from short_bot.db import init_db, record_short, start_run, finish_run
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
    # Seed: 2 shorts today + 1 yesterday + 1 failed run
    record_short(eng, channel="ch", rss_item_guid="g1", title="A",
                 file_path="output/ch/a.mp4", duration_s=6,
                 script_json="{}", render_ms=1000)
    record_short(eng, channel="ch", rss_item_guid="g2", title="B",
                 file_path="output/ch/b.mp4", duration_s=6,
                 script_json="{}", render_ms=1000)
    rid = start_run(eng, "ch", trigger="cron", log_path="x.log")
    finish_run(eng, rid, status="failed", short_id=None, error="boom")
    return create_app(config_dir=cfg_dir, db_path=db_path, scheduler=False)


def test_dashboard_shows_total_count(app):
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "2" in body  # 2 shorts total


def test_dashboard_shows_channel_count(app):
    client = app.test_client()
    resp = client.get("/")
    body = resp.data.decode("utf-8")
    assert "Kanal" in body or "channel" in body.lower()


def test_dashboard_shows_failed_runs_count(app):
    client = app.test_client()
    resp = client.get("/")
    body = resp.data.decode("utf-8")
    assert "1" in body  # 1 failed run


def test_dashboard_shows_last_hour_card(app):
    client = app.test_client()
    body = client.get("/").data.decode("utf-8")
    assert "Son 1 saat" in body
    assert 'href="/shorts?since=1h"' in body


def test_dashboard_shows_youtube_card(app):
    client = app.test_client()
    body = client.get("/").data.decode("utf-8")
    assert "YouTube" in body
    assert 'href="/shorts?youtube=yes"' in body


def test_dashboard_shows_quick_filter_chips(app):
    client = app.test_client()
    body = client.get("/").data.decode("utf-8")
    assert "Hızlı filtre" in body
    assert 'href="/shorts?since=today"' in body
    assert 'href="/shorts?youtube=no"' in body


# ---- Clear-errors button + endpoint ----------------------------------------

def test_dashboard_shows_clear_errors_button(app):
    """When there are recent errors, panel must offer a 'Temizle' button."""
    client = app.test_client()
    body = client.get("/").data.decode("utf-8")
    assert "Son 24 saat" in body
    assert "Temizle" in body
    assert "/dashboard/clear-errors" in body


def test_clear_errors_deletes_failed_runs(app, tmp_path):
    """POST /dashboard/clear-errors → failed runs gone; dashboard hides panel."""
    client = app.test_client()
    # Confirm panel is shown before clearing
    body = client.get("/").data.decode("utf-8")
    assert "Son 24 saat" in body

    r = client.post("/dashboard/clear-errors", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")

    # Panel should be gone after the clear
    body = client.get("/").data.decode("utf-8")
    assert "Son 24 saat" not in body


def test_clear_errors_htmx_returns_redirect_header(app):
    client = app.test_client()
    r = client.post("/dashboard/clear-errors",
                     headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers.get("HX-Redirect") == "/"


def test_clear_errors_when_no_errors_returns_ok(app, tmp_path):
    """No failed runs → endpoint still 200/redirect with info flash."""
    client = app.test_client()
    # First clear: deletes the seeded failed run
    client.post("/dashboard/clear-errors")
    # Second clear: nothing to delete, must still succeed
    r = client.post("/dashboard/clear-errors", follow_redirects=False)
    assert r.status_code == 302


def test_clear_recent_failed_runs_helper(tmp_path):
    """Direct helper test: only failed runs within window are deleted."""
    from short_bot.db import init_db, start_run, finish_run, clear_recent_failed_runs
    eng = init_db(tmp_path / "x.sqlite")
    # 1 failed, 1 success — only failed should disappear
    rid_fail = start_run(eng, "ch", trigger="cron", log_path="x.log")
    finish_run(eng, rid_fail, status="failed", short_id=None, error="boom")
    rid_ok = start_run(eng, "ch", trigger="cron", log_path="y.log")
    finish_run(eng, rid_ok, status="success", short_id=None)

    deleted = clear_recent_failed_runs(eng, hours=24)
    assert deleted == 1

    # Success run still exists
    from sqlalchemy import text
    with eng.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM runs")).scalar()
    assert n == 1
