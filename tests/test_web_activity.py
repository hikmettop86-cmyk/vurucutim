import pytest

from short_bot.db import init_db, start_run, finish_run, record_short
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "x.sqlite"
    eng = init_db(db_path)
    rid = start_run(eng, "ch1", trigger="manual", log_path="x.log")
    finish_run(eng, rid, status="success", short_id=None, error=None)
    record_short(eng, channel="ch1", rss_item_guid="g1", title="My Short",
                  file_path="output/ch1/a.mp4", duration_s=6,
                  script_json="{}", render_ms=1)
    return create_app(config_dir=cfg_dir, db_path=db_path,
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)


def test_activity_page_returns_200(app):
    resp = app.test_client().get("/activity")
    assert resp.status_code == 200


def test_activity_page_renders_event_in_feed(app):
    body = app.test_client().get("/activity").data.decode("utf-8")
    # The seeded short and run should both appear
    assert "My Short" in body
    assert "ch1" in body


def test_nav_has_activity_link(app):
    body = app.test_client().get("/").data.decode("utf-8")
    assert 'href="/activity"' in body
    assert "Akış" in body
