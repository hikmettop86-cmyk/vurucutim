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
