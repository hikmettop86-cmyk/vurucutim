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


def test_activity_page_shows_summary_cards(app):
    body = app.test_client().get("/activity").data.decode("utf-8")
    # Cards labels (Turkish)
    assert "Run" in body
    assert "Short" in body
    assert "YouTube" in body or "YT" in body
    assert "Hata" in body


def test_activity_page_shows_live_runs_section(app):
    body = app.test_client().get("/activity").data.decode("utf-8")
    # The seeded data has no running run, so we expect the empty-state copy
    assert "Şu an çalışan" in body or "Çalışan" in body


def test_activity_page_shows_filter_controls(app):
    body = app.test_client().get("/activity").data.decode("utf-8")
    assert 'name="channel"' in body
    assert 'name="type"' in body
    assert 'name="since"' in body


def test_activity_errors_card_pulses_when_failed_runs_present(app, tmp_path):
    """When errors_24h > 0, the errors card has animate-pulse class."""
    from short_bot.db import init_db, start_run, finish_run
    db_path = app.config["SHORTBOT_DB_PATH"]
    eng = init_db(db_path)
    rid = start_run(eng, "chF", trigger="manual", log_path="f.log")
    finish_run(eng, rid, status="failed", short_id=None, error="x")

    body = app.test_client().get("/activity").data.decode("utf-8")
    assert "animate-pulse" in body


def test_activity_feed_partial_returns_only_feed_html(app):
    """The /activity/feed endpoint returns the rows only — no nav, no h1, no
    summary cards. htmx swaps it into #activity-feed."""
    resp = app.test_client().get("/activity/feed")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "<nav" not in body
    assert "<h1" not in body
    assert "Şu an çalışan" not in body  # not in this partial
    # Feed content present
    assert "ch1" in body


def test_activity_live_runs_partial_returns_only_live_runs(app):
    resp = app.test_client().get("/activity/live-runs")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "<nav" not in body
    assert "<h1" not in body
    # No running runs in seeded data
    assert "Şu an çalışan run yok" in body or "çalışan" in body.lower()


def test_activity_feed_partial_respects_filters(app):
    """Filter query params apply to the partial."""
    body = app.test_client().get("/activity/feed?type=short").data.decode("utf-8")
    assert "My Short" in body  # short event still visible


def test_activity_page_includes_htmx_attrs_for_auto_refresh(app):
    body = app.test_client().get("/activity").data.decode("utf-8")
    # Feed and live runs should both auto-refresh via htmx polling
    assert 'hx-get="/activity/feed"' in body
    assert 'hx-get="/activity/live-runs"' in body
    assert "every 10s" in body or 'every 10s"' in body
    assert "every 5s" in body or 'every 5s"' in body


def test_activity_feed_partial_renders_load_more_button_when_full_page(app, tmp_path):
    """When the feed returns exactly the limit, render a 'daha eski yükle' link
    with cursor + filter params so the operator can paginate."""
    from short_bot.db import init_db, start_run, finish_run
    db_path = app.config["SHORTBOT_DB_PATH"]
    eng = init_db(db_path)
    # Seed enough rows to fill a small page (we'll override limit via query param)
    for i in range(5):
        rid = start_run(eng, f"ch{i}", trigger="manual", log_path=f"x{i}.log")
        finish_run(eng, rid, status="success", short_id=None, error=None)

    # Hit the partial with limit=2; expect "daha eski" link with cursor param
    body = app.test_client().get("/activity/feed?limit=2").data.decode("utf-8")
    assert "daha eski" in body.lower()
    assert "cursor=" in body


def test_activity_feed_empty_no_filters_shows_henuz_message(app, tmp_path):
    """No events at all + no filters → 'Henüz aktivite yok' empty-state copy."""
    # Wipe seeded data
    from short_bot.db import init_db
    db_path = app.config["SHORTBOT_DB_PATH"]
    eng = init_db(db_path)
    from short_bot.db import runs as runs_table, shorts as shorts_table, youtube_uploads
    with eng.begin() as conn:
        conn.execute(runs_table.delete())
        conn.execute(youtube_uploads.delete())
        conn.execute(shorts_table.delete())

    body = app.test_client().get("/activity/feed").data.decode("utf-8")
    assert "Henüz aktivite yok" in body
    # Should NOT show the filtered-empty message
    assert "Bu filtre için sonuç yok" not in body


def test_activity_feed_empty_with_filters_shows_temizle_link(app, tmp_path):
    """No matching events but filter active → 'Bu filtre için sonuç yok' + temizle link."""
    body = app.test_client().get("/activity/feed?channel=__nonexistent__").data.decode("utf-8")
    assert "Bu filtre için sonuç yok" in body
    assert 'href="/activity"' in body  # the "temizle" link
