from datetime import datetime, timedelta, timezone

import pytest

from short_bot.db import init_db, start_run, finish_run


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "x.sqlite")


def _utc_now():
    return datetime.now(timezone.utc)


def test_activity_event_dataclass_shape():
    from short_bot.web.activity import ActivityEvent
    e = ActivityEvent(
        timestamp=_utc_now(), type="run", channel="ch1",
        title="t", detail="d", status="success",
        link="/logs?channel=ch1", icon="🔍",
    )
    # Frozen — must reject mutation
    with pytest.raises(Exception):
        e.title = "other"


def test_build_activity_events_includes_successful_run(eng):
    rid = start_run(eng, "ch1", trigger="manual", log_path="x.log")
    finish_run(eng, rid, status="success", short_id=None, error=None)

    from short_bot.web.activity import build_activity_events
    events = build_activity_events(eng, since=_utc_now() - timedelta(hours=1))
    runs = [e for e in events if e.type == "run"]
    assert len(runs) == 1
    assert runs[0].channel == "ch1"
    assert runs[0].status == "success"


def test_build_activity_events_failed_run_becomes_error_type(eng):
    rid = start_run(eng, "ch1", trigger="cron", log_path="x.log")
    finish_run(eng, rid, status="failed", short_id=None, error="boom")

    from short_bot.web.activity import build_activity_events
    events = build_activity_events(eng, since=_utc_now() - timedelta(hours=1))
    errors = [e for e in events if e.type == "error"]
    assert len(errors) == 1
    assert errors[0].channel == "ch1"
    assert errors[0].status == "failed"
    assert "boom" in errors[0].detail


def test_build_activity_events_excludes_runs_before_since(eng):
    rid = start_run(eng, "ch1", trigger="manual", log_path="x.log")
    finish_run(eng, rid, status="success", short_id=None, error=None)

    from short_bot.web.activity import build_activity_events
    # since 1 hour in the future → no events
    events = build_activity_events(eng, since=_utc_now() + timedelta(hours=1))
    assert events == []


def test_build_activity_events_running_run_not_emitted_as_event(eng):
    """Running runs (ended_at IS NULL) belong on the live-runs panel, not the feed."""
    start_run(eng, "ch1", trigger="manual", log_path="x.log")  # not finished

    from short_bot.web.activity import build_activity_events
    events = build_activity_events(eng, since=_utc_now() - timedelta(hours=1))
    assert events == []


from short_bot.db import record_short


def test_build_activity_events_includes_short_event(eng):
    record_short(eng, channel="ch1", rss_item_guid="g1", title="My Title",
                  file_path="output/ch1/a.mp4", duration_s=6,
                  script_json="{}", render_ms=1000)

    from short_bot.web.activity import build_activity_events
    from datetime import datetime, timedelta, timezone
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    shorts = [e for e in events if e.type == "short"]
    assert len(shorts) == 1
    s = shorts[0]
    assert s.channel == "ch1"
    assert "My Title" in s.title or "My Title" in s.detail
    assert s.status == "success"
    assert s.link.startswith("/shorts/")


def test_build_activity_events_excludes_deleted_shorts(eng):
    """Soft-deleted shorts must NOT appear in the feed."""
    from datetime import datetime, timezone
    sid = record_short(eng, channel="ch1", rss_item_guid="g1", title="Del",
                       file_path="output/ch1/d.mp4", duration_s=6,
                       script_json="{}", render_ms=1)
    # Soft-delete it directly via SQL
    from short_bot.db import shorts as shorts_table
    with eng.begin() as conn:
        conn.execute(
            shorts_table.update().where(shorts_table.c.id == sid).values(
                deleted_at=datetime.now(timezone.utc),
            )
        )

    from short_bot.web.activity import build_activity_events
    from datetime import timedelta
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert all(e.type != "short" for e in events)


def test_build_activity_events_youtube_success_emits_youtube_event(eng):
    """A successful upload emits a 'youtube' event with the video URL."""
    sid = record_short(eng, channel="ch1", rss_item_guid="g1", title="t",
                       file_path="output/ch1/a.mp4", duration_s=6,
                       script_json="{}", render_ms=1)
    from short_bot.db import youtube_uploads
    from datetime import datetime, timezone
    with eng.begin() as conn:
        conn.execute(youtube_uploads.insert().values(
            short_id=sid, video_id="vid123", video_url="https://yt/v?id=vid123",
            status="success", error=None,
            uploaded_at=datetime.now(timezone.utc),
        ))

    from short_bot.web.activity import build_activity_events
    from datetime import timedelta
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    yt = [e for e in events if e.type == "youtube"]
    assert len(yt) == 1
    assert yt[0].channel == "ch1"
    assert "vid123" in yt[0].detail or "vid123" in yt[0].link


def test_build_activity_events_youtube_failed_emits_error_event(eng):
    sid = record_short(eng, channel="ch1", rss_item_guid="g1", title="t",
                       file_path="output/ch1/a.mp4", duration_s=6,
                       script_json="{}", render_ms=1)
    from short_bot.db import youtube_uploads
    from datetime import datetime, timezone
    with eng.begin() as conn:
        conn.execute(youtube_uploads.insert().values(
            short_id=sid, video_id=None, video_url=None,
            status="failed", error="quota exceeded",
            uploaded_at=datetime.now(timezone.utc),
        ))

    from short_bot.web.activity import build_activity_events
    from datetime import timedelta
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    yt_errors = [e for e in events
                 if e.type == "error" and "YouTube" in e.title]
    assert len(yt_errors) == 1
    assert "quota" in yt_errors[0].detail


def test_build_activity_events_filters_by_channel(eng):
    rid1 = start_run(eng, "ch1", trigger="manual", log_path="x.log")
    finish_run(eng, rid1, status="success", short_id=None, error=None)
    rid2 = start_run(eng, "ch2", trigger="manual", log_path="y.log")
    finish_run(eng, rid2, status="success", short_id=None, error=None)

    from short_bot.web.activity import build_activity_events
    from datetime import datetime, timedelta, timezone
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
        channel="ch1",
    )
    assert len(events) == 1
    assert events[0].channel == "ch1"


def test_build_activity_events_filters_by_type(eng):
    rid = start_run(eng, "ch1", trigger="manual", log_path="x.log")
    finish_run(eng, rid, status="success", short_id=None, error=None)
    record_short(eng, channel="ch1", rss_item_guid="g1", title="t",
                  file_path="output/ch1/a.mp4", duration_s=6,
                  script_json="{}", render_ms=1)

    from short_bot.web.activity import build_activity_events
    from datetime import datetime, timedelta, timezone
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
        types=("run",),
    )
    assert all(e.type == "run" for e in events)
    assert len(events) == 1


def test_build_activity_events_filters_by_status(eng):
    rid_ok = start_run(eng, "ch1", trigger="manual", log_path="ok.log")
    finish_run(eng, rid_ok, status="success", short_id=None, error=None)
    rid_bad = start_run(eng, "ch1", trigger="manual", log_path="bad.log")
    finish_run(eng, rid_bad, status="failed", short_id=None, error="boom")

    from short_bot.web.activity import build_activity_events
    from datetime import datetime, timedelta, timezone
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
        status="failed",
    )
    assert len(events) == 1
    assert events[0].status == "failed"


def test_build_activity_events_filter_combinations(eng):
    """All filters AND together. channel=ch1 + type=run + status=success
    excludes a ch1 short (wrong type) and a ch1 failed run (wrong status)."""
    # ch1 success run → INCLUDED
    rid = start_run(eng, "ch1", trigger="manual", log_path="x.log")
    finish_run(eng, rid, status="success", short_id=None, error=None)
    # ch1 short → wrong type, excluded
    record_short(eng, channel="ch1", rss_item_guid="g1", title="t",
                  file_path="output/ch1/a.mp4", duration_s=6,
                  script_json="{}", render_ms=1)
    # ch1 failed run → wrong status, excluded
    rid2 = start_run(eng, "ch1", trigger="manual", log_path="y.log")
    finish_run(eng, rid2, status="failed", short_id=None, error="x")
    # ch2 success run → wrong channel, excluded
    rid3 = start_run(eng, "ch2", trigger="manual", log_path="z.log")
    finish_run(eng, rid3, status="success", short_id=None, error=None)

    from short_bot.web.activity import build_activity_events
    from datetime import datetime, timedelta, timezone
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
        channel="ch1", types=("run",), status="success",
    )
    assert len(events) == 1
    assert events[0].channel == "ch1"
    assert events[0].type == "run"
    assert events[0].status == "success"


def test_build_activity_events_respects_limit(eng):
    for i in range(5):
        rid = start_run(eng, f"ch{i}", trigger="manual", log_path=f"x{i}.log")
        finish_run(eng, rid, status="success", short_id=None, error=None)

    from short_bot.web.activity import build_activity_events
    from datetime import datetime, timedelta, timezone
    events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
        limit=3,
    )
    assert len(events) == 3


def test_build_activity_events_cursor_returns_strictly_older(eng):
    """Cursor = timestamp; only events strictly OLDER than cursor are returned.
    Combined with sort DESC, this gives stable 'load more' pagination."""
    import time
    for i in range(3):
        rid = start_run(eng, f"ch{i}", trigger="manual", log_path=f"x{i}.log")
        finish_run(eng, rid, status="success", short_id=None, error=None)
        time.sleep(0.01)  # ensure distinct timestamps

    from short_bot.web.activity import build_activity_events
    from datetime import datetime, timedelta, timezone
    all_events = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert len(all_events) == 3
    # First page: limit 2
    page1 = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
        limit=2,
    )
    assert len(page1) == 2
    # Cursor = timestamp of LAST item in page1
    cursor = page1[-1].timestamp
    page2 = build_activity_events(
        eng, since=datetime.now(timezone.utc) - timedelta(hours=1),
        limit=2, cursor=cursor,
    )
    assert len(page2) == 1
    # No overlap: page2 events are older than cursor
    for e in page2:
        assert e.timestamp < cursor


def test_compute_summary_24h_counts_all_buckets(eng):
    # 1 success run, 1 failed run, 1 short, 1 successful YT, 1 failed YT
    r1 = start_run(eng, "ch1", trigger="manual", log_path="a.log")
    finish_run(eng, r1, status="success", short_id=None, error=None)
    r2 = start_run(eng, "ch1", trigger="manual", log_path="b.log")
    finish_run(eng, r2, status="failed", short_id=None, error="x")
    sid = record_short(eng, channel="ch1", rss_item_guid="g", title="t",
                       file_path="output/ch1/a.mp4", duration_s=6,
                       script_json="{}", render_ms=1)
    from short_bot.db import youtube_uploads
    from datetime import datetime, timezone
    with eng.begin() as conn:
        conn.execute(youtube_uploads.insert().values(
            short_id=sid, video_id="v", video_url="u",
            status="success", error=None,
            uploaded_at=datetime.now(timezone.utc),
        ))
        conn.execute(youtube_uploads.insert().values(
            short_id=sid, video_id=None, video_url=None,
            status="failed", error="quota",
            uploaded_at=datetime.now(timezone.utc),
        ))

    from short_bot.web.activity import compute_summary_24h
    s = compute_summary_24h(eng)
    assert s.runs_24h == 2
    assert s.runs_success_24h == 1
    assert s.runs_failed_24h == 1
    assert s.shorts_24h == 1
    assert s.youtube_success_24h == 1
    # errors = failed runs + failed YT = 2
    assert s.errors_24h == 2


def test_list_running_runs_returns_only_unfinished(eng):
    # Finished run
    r1 = start_run(eng, "ch1", trigger="manual", log_path="a.log")
    finish_run(eng, r1, status="success", short_id=None, error=None)
    # Running run
    r2 = start_run(eng, "ch2", trigger="manual", log_path="b.log")

    from short_bot.web.activity import list_running_runs
    rows = list_running_runs(eng)
    assert len(rows) == 1
    assert rows[0].channel == "ch2"


def test_list_running_runs_orders_by_started_at_desc(eng):
    import time
    r1 = start_run(eng, "ch_old", trigger="manual", log_path="a.log")
    time.sleep(0.01)
    r2 = start_run(eng, "ch_new", trigger="manual", log_path="b.log")

    from short_bot.web.activity import list_running_runs
    rows = list_running_runs(eng)
    assert len(rows) == 2
    assert rows[0].channel == "ch_new"
    assert rows[1].channel == "ch_old"
