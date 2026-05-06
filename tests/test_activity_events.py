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
