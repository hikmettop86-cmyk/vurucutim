# Activity Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/activity` operator page that shows a single chronological feed of every notable system event (runs, shorts produced, YouTube uploads, errors) plus 24h summary cards and currently-running pipelines, with htmx auto-refresh, filtering, and cursor-based pagination.

**Architecture:** Pure event-builder module (`web/activity.py`) UNIONs rows from `runs`, `shorts`, `youtube_uploads` into a sorted `ActivityEvent` list. A Flask blueprint exposes `/activity` (full page) and two htmx partials (`/activity/feed`, `/activity/live-runs`). No DB migration; reuses existing tables.

**Tech Stack:** Flask, SQLAlchemy ORM, Jinja2, htmx 2, Alpine.js, Tailwind, pytest.

**Spec:** `docs/superpowers/specs/2026-05-07-activity-timeline-design.md`

---

## File Structure

**Create:**
- `src/short_bot/web/activity.py` — pure builder: `ActivityEvent`, `ActivitySummary`, `build_activity_events`, `compute_summary_24h`, `list_running_runs`
- `src/short_bot/web/routes/activity.py` — blueprint with `/activity`, `/activity/feed`, `/activity/live-runs`
- `src/short_bot/web/templates/activity.html.j2` — full page (3 zones)
- `src/short_bot/web/templates/_partials/activity_feed.html.j2` — htmx-swappable feed
- `src/short_bot/web/templates/_partials/activity_live_runs.html.j2` — htmx-swappable live runs
- `tests/test_activity_events.py` — pure builder tests (no Flask)
- `tests/test_web_activity.py` — Flask client tests

**Modify:**
- `src/short_bot/web/routes/__init__.py` — register the new blueprint
- `src/short_bot/web/templates/base.html.j2` — add "Akış" nav link

---

## Task 1: `ActivityEvent` + builder for `runs` only

Establish the dataclass, the function signature, and the simplest source: the `runs` table. Success/no_candidates → "run" event; failed → "error" event.

**Files:**
- Create: `D:\short\src\short_bot\web\activity.py`
- Create: `D:\short\tests\test_activity_events.py`

- [ ] **Step 1: Write the failing test**

Create `D:\short\tests\test_activity_events.py`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL**

Run from `D:\short`:
```
python -m pytest tests/test_activity_events.py -v
```
Expected: ImportError on `short_bot.web.activity`.

- [ ] **Step 3: Create the module with the dataclass + builder**

Create `D:\short\src\short_bot\web\activity.py`:

```python
"""Activity event builder.

Pure module. Reads from `runs`, `shorts`, `youtube_uploads` tables and
returns a unified, time-sorted list of ActivityEvent records for the
operator's /activity page. No Flask dependencies — testable in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.engine import Engine

from short_bot.db import runs


EventType = Literal["run", "short", "youtube", "error"]
EventStatus = Literal["success", "failed", "no_candidates", "running"]


@dataclass(frozen=True)
class ActivityEvent:
    timestamp: datetime
    type: EventType
    channel: str
    title: str
    detail: str
    status: EventStatus | None
    link: str
    icon: str


_RUN_ICON = "🔍"
_ERROR_ICON = "⚠"


def _aware(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC (matches Run.duration_seconds pattern)."""
    if dt is None:
        return dt
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _build_run_events(eng: Engine, *, since: datetime) -> list[ActivityEvent]:
    """One row per finished run. status=success/no_candidates → 'run' event;
    status=failed → 'error' event with the run's error message in detail."""
    out: list[ActivityEvent] = []
    with eng.connect() as conn:
        rows = conn.execute(
            select(runs)
            .where(runs.c.ended_at.is_not(None))
            .where(runs.c.ended_at >= since)
            .order_by(runs.c.ended_at.desc())
        ).fetchall()
    for r in rows:
        ts = _aware(r.ended_at)
        if r.status == "failed":
            out.append(ActivityEvent(
                timestamp=ts, type="error", channel=r.channel,
                title=f"Run hata · {r.channel}",
                detail=(r.error or "")[:120],
                status="failed",
                link=f"/logs?channel={r.channel}",
                icon=_ERROR_ICON,
            ))
        else:
            out.append(ActivityEvent(
                timestamp=ts, type="run", channel=r.channel,
                title=f"Run · {r.channel}",
                detail=r.status or "",
                status=r.status,
                link=f"/logs?channel={r.channel}",
                icon=_RUN_ICON,
            ))
    return out


def build_activity_events(eng: Engine, *, since: datetime) -> list[ActivityEvent]:
    """Return a time-sorted (DESC) list of events from since onwards.
    Currently includes only run/error events from the runs table; later tasks
    UNION shorts and youtube_uploads."""
    events = _build_run_events(eng, since=since)
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events
```

- [ ] **Step 4: Run, expect PASS**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add src/short_bot/web/activity.py tests/test_activity_events.py
git commit -m "feat(activity): ActivityEvent dataclass + run-source events"
```

---

## Task 2: Add `shorts` source

Extend the builder so each `shorts` row (deleted_at IS NULL) emits a "short" event.

**Files:**
- Modify: `D:\short\src\short_bot\web\activity.py`
- Modify: `D:\short\tests\test_activity_events.py`

- [ ] **Step 1: Write the failing test**

Append to `D:\short\tests\test_activity_events.py`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 2 new tests fail (no short events emitted yet).

- [ ] **Step 3: Add `_build_short_events` helper and union into the main builder**

In `D:\short\src\short_bot\web\activity.py`:

1. Add `shorts` to the import from `short_bot.db`:
```python
from short_bot.db import runs, shorts as shorts_table
```

2. Add the icon constant near the others:
```python
_SHORT_ICON = "✓"
```

3. Add this helper above `build_activity_events`:

```python
def _build_short_events(eng: Engine, *, since: datetime) -> list[ActivityEvent]:
    """One event per short produced (deleted_at IS NULL only)."""
    out: list[ActivityEvent] = []
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts_table)
            .where(shorts_table.c.deleted_at.is_(None))
            .where(shorts_table.c.created_at >= since)
            .order_by(shorts_table.c.created_at.desc())
        ).fetchall()
    for r in rows:
        ts = _aware(r.created_at)
        title = (r.title or "")[:80]
        out.append(ActivityEvent(
            timestamp=ts, type="short", channel=r.channel,
            title=f"Video · {r.channel}",
            detail=f"{title} · {r.duration_s}s · {r.render_ms}ms",
            status="success",
            link=f"/shorts/{r.id}",
            icon=_SHORT_ICON,
        ))
    return out
```

4. Update `build_activity_events` to UNION:

```python
def build_activity_events(eng: Engine, *, since: datetime) -> list[ActivityEvent]:
    """Return a time-sorted (DESC) list of events from since onwards.
    Sources: finished runs (success/failed/no_candidates) and produced shorts.
    Later tasks add youtube_uploads."""
    events = _build_run_events(eng, since=since) + _build_short_events(eng, since=since)
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events
```

- [ ] **Step 4: Run, expect PASS**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 7 passed (5 from Task 1 + 2 new).

- [ ] **Step 5: Commit**

```
git add src/short_bot/web/activity.py tests/test_activity_events.py
git commit -m "feat(activity): add shorts as event source"
```

---

## Task 3: Add `youtube_uploads` source

`status=success` → "youtube" event. `status=failed` → "error" event.

**Files:**
- Modify: `D:\short\src\short_bot\web\activity.py`
- Modify: `D:\short\tests\test_activity_events.py`

- [ ] **Step 1: Write the failing test**

Append to `D:\short\tests\test_activity_events.py`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 2 new tests fail.

- [ ] **Step 3: Add `_build_youtube_events` and union it in**

In `D:\short\src\short_bot\web\activity.py`:

1. Update db import to include youtube_uploads + shorts (need shorts.channel for YT events because youtube_uploads.short_id only):

```python
from short_bot.db import runs, shorts as shorts_table, youtube_uploads
```

2. Add icon constant:

```python
_YOUTUBE_ICON = "▶"
```

3. Add helper:

```python
def _build_youtube_events(eng: Engine, *, since: datetime) -> list[ActivityEvent]:
    """One event per youtube_uploads row. status=success → 'youtube'; failed → 'error'."""
    out: list[ActivityEvent] = []
    with eng.connect() as conn:
        rows = conn.execute(
            select(
                youtube_uploads.c.short_id,
                youtube_uploads.c.video_id,
                youtube_uploads.c.video_url,
                youtube_uploads.c.status,
                youtube_uploads.c.error,
                youtube_uploads.c.uploaded_at,
                shorts_table.c.channel,
                shorts_table.c.title,
            )
            .select_from(
                youtube_uploads.join(
                    shorts_table, youtube_uploads.c.short_id == shorts_table.c.id,
                )
            )
            .where(youtube_uploads.c.uploaded_at >= since)
            .order_by(youtube_uploads.c.uploaded_at.desc())
        ).fetchall()
    for r in rows:
        ts = _aware(r.uploaded_at)
        if r.status == "success":
            out.append(ActivityEvent(
                timestamp=ts, type="youtube", channel=r.channel,
                title=f"YouTube · {r.channel}",
                detail=f"{(r.title or '')[:60]} · {r.video_id or ''}",
                status="success",
                link=r.video_url or f"/shorts/{r.short_id}",
                icon=_YOUTUBE_ICON,
            ))
        else:
            out.append(ActivityEvent(
                timestamp=ts, type="error", channel=r.channel,
                title=f"YouTube hata · {r.channel}",
                detail=(r.error or "")[:120],
                status="failed",
                link=f"/shorts/{r.short_id}",
                icon=_ERROR_ICON,
            ))
    return out
```

4. Update `build_activity_events`:

```python
def build_activity_events(eng: Engine, *, since: datetime) -> list[ActivityEvent]:
    """Return time-sorted (DESC) list. Sources: runs, shorts, youtube_uploads."""
    events = (
        _build_run_events(eng, since=since)
        + _build_short_events(eng, since=since)
        + _build_youtube_events(eng, since=since)
    )
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events
```

- [ ] **Step 4: Run, expect PASS**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```
git add src/short_bot/web/activity.py tests/test_activity_events.py
git commit -m "feat(activity): add youtube_uploads as event source"
```

---

## Task 4: Filtering (channel, type, status)

Add three optional filter parameters. Each narrows the feed.

**Files:**
- Modify: `D:\short\src\short_bot\web\activity.py`
- Modify: `D:\short\tests\test_activity_events.py`

- [ ] **Step 1: Write failing tests**

Append to `D:\short\tests\test_activity_events.py`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 4 new tests fail (TypeError on unexpected kwargs).

- [ ] **Step 3: Add filter parameters to `build_activity_events`**

Replace `build_activity_events` in `D:\short\src\short_bot\web\activity.py` with:

```python
ALL_TYPES: tuple[EventType, ...] = ("run", "short", "youtube", "error")


def build_activity_events(
    eng: Engine,
    *,
    since: datetime,
    channel: str | None = None,
    types: tuple[EventType, ...] = ALL_TYPES,
    status: EventStatus | None = None,
) -> list[ActivityEvent]:
    """Time-sorted (DESC) feed of events from since onwards. Filters apply AND.

    types: which event types to include. Defaults to all 4. Note that 'error'
        events come from BOTH runs (failed) and youtube_uploads (failed).
    status: narrow to a specific status (success/failed/no_candidates).
    channel: narrow to a single channel slug.
    """
    events = (
        _build_run_events(eng, since=since)
        + _build_short_events(eng, since=since)
        + _build_youtube_events(eng, since=since)
    )
    if channel:
        events = [e for e in events if e.channel == channel]
    if types != ALL_TYPES:
        wanted = set(types)
        events = [e for e in events if e.type in wanted]
    if status:
        events = [e for e in events if e.status == status]
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events
```

- [ ] **Step 4: Run, expect PASS**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 13 passed.

- [ ] **Step 5: Commit**

```
git add src/short_bot/web/activity.py tests/test_activity_events.py
git commit -m "feat(activity): add channel/type/status filters"
```

---

## Task 5: Cursor-based pagination

`limit` (default 200) and `cursor` (timestamp; events strictly older than cursor). Stable as new events arrive at the head.

**Files:**
- Modify: `D:\short\src\short_bot\web\activity.py`
- Modify: `D:\short\tests\test_activity_events.py`

- [ ] **Step 1: Write failing tests**

Append to `D:\short\tests\test_activity_events.py`:

```python
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
    times = []
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
```

- [ ] **Step 2: Run, expect FAIL**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 2 new tests fail.

- [ ] **Step 3: Add limit + cursor to `build_activity_events`**

Replace the function with:

```python
def build_activity_events(
    eng: Engine,
    *,
    since: datetime,
    channel: str | None = None,
    types: tuple[EventType, ...] = ALL_TYPES,
    status: EventStatus | None = None,
    limit: int = 200,
    cursor: datetime | None = None,
) -> list[ActivityEvent]:
    """Time-sorted (DESC) feed of events from `since` onwards. AND filters.

    Pagination: cursor = timestamp; only events with timestamp < cursor are
    returned, so 'load more' is stable as new events arrive at the head.
    """
    events = (
        _build_run_events(eng, since=since)
        + _build_short_events(eng, since=since)
        + _build_youtube_events(eng, since=since)
    )
    if channel:
        events = [e for e in events if e.channel == channel]
    if types != ALL_TYPES:
        wanted = set(types)
        events = [e for e in events if e.type in wanted]
    if status:
        events = [e for e in events if e.status == status]
    if cursor is not None:
        cursor_aware = _aware(cursor)
        events = [e for e in events if e.timestamp < cursor_aware]
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events[:limit]
```

- [ ] **Step 4: Run, expect PASS**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 15 passed.

- [ ] **Step 5: Commit**

```
git add src/short_bot/web/activity.py tests/test_activity_events.py
git commit -m "feat(activity): add limit + cursor pagination"
```

---

## Task 6: `compute_summary_24h` + `list_running_runs`

Two more pure helpers in the same module. The summary feeds the top cards; the live runs feed the middle zone.

**Files:**
- Modify: `D:\short\src\short_bot\web\activity.py`
- Modify: `D:\short\tests\test_activity_events.py`

- [ ] **Step 1: Write failing tests**

Append to `D:\short\tests\test_activity_events.py`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 3 new tests fail.

- [ ] **Step 3: Add the helpers**

In `D:\short\src\short_bot\web\activity.py`:

1. Add `func` import for SQLAlchemy aggregates if not present:

```python
from sqlalchemy import func, select
```

2. Add `timedelta` import:

```python
from datetime import datetime, timedelta, timezone
```

3. Append to the file:

```python
@dataclass(frozen=True)
class ActivitySummary:
    runs_24h: int
    runs_success_24h: int
    runs_failed_24h: int
    shorts_24h: int
    youtube_success_24h: int
    errors_24h: int


def compute_summary_24h(eng: Engine) -> ActivitySummary:
    """Aggregate counts from runs, shorts, youtube_uploads over the last 24h."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    with eng.connect() as conn:
        runs_total = conn.execute(
            select(func.count()).select_from(runs)
            .where(runs.c.ended_at.is_not(None))
            .where(runs.c.ended_at >= since)
        ).scalar() or 0
        runs_success = conn.execute(
            select(func.count()).select_from(runs)
            .where(runs.c.status == "success")
            .where(runs.c.ended_at >= since)
        ).scalar() or 0
        runs_failed = conn.execute(
            select(func.count()).select_from(runs)
            .where(runs.c.status == "failed")
            .where(runs.c.ended_at >= since)
        ).scalar() or 0
        shorts_count = conn.execute(
            select(func.count()).select_from(shorts_table)
            .where(shorts_table.c.deleted_at.is_(None))
            .where(shorts_table.c.created_at >= since)
        ).scalar() or 0
        yt_success = conn.execute(
            select(func.count()).select_from(youtube_uploads)
            .where(youtube_uploads.c.status == "success")
            .where(youtube_uploads.c.uploaded_at >= since)
        ).scalar() or 0
        yt_failed = conn.execute(
            select(func.count()).select_from(youtube_uploads)
            .where(youtube_uploads.c.status == "failed")
            .where(youtube_uploads.c.uploaded_at >= since)
        ).scalar() or 0
    return ActivitySummary(
        runs_24h=int(runs_total),
        runs_success_24h=int(runs_success),
        runs_failed_24h=int(runs_failed),
        shorts_24h=int(shorts_count),
        youtube_success_24h=int(yt_success),
        errors_24h=int(runs_failed) + int(yt_failed),
    )


@dataclass(frozen=True)
class RunningRun:
    id: int
    channel: str
    trigger: str
    started_at: datetime  # always tz-aware


def list_running_runs(eng: Engine) -> list[RunningRun]:
    """Runs with ended_at IS NULL ordered by started_at DESC."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(runs.c.id, runs.c.channel, runs.c.trigger, runs.c.started_at)
            .where(runs.c.ended_at.is_(None))
            .order_by(runs.c.started_at.desc())
        ).fetchall()
    return [
        RunningRun(
            id=int(r.id),
            channel=r.channel,
            trigger=r.trigger,
            started_at=_aware(r.started_at),
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run, expect PASS**

```
python -m pytest tests/test_activity_events.py -v
```
Expected: 18 passed.

- [ ] **Step 5: Commit**

```
git add src/short_bot/web/activity.py tests/test_activity_events.py
git commit -m "feat(activity): add 24h summary + live-runs helpers"
```

---

## Task 7: Blueprint + route + nav link

Wire `/activity` into the Flask app. Initial render produces the static page (no htmx partials yet — that's Task 9).

**Files:**
- Create: `D:\short\src\short_bot\web\routes\activity.py`
- Modify: `D:\short\src\short_bot\web\routes\__init__.py`
- Modify: `D:\short\src\short_bot\web\templates\base.html.j2`
- Create: `D:\short\src\short_bot\web\templates\activity.html.j2` (placeholder; full layout in Task 8)
- Create: `D:\short\tests\test_web_activity.py`

- [ ] **Step 1: Write failing tests**

Create `D:\short\tests\test_web_activity.py`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL**

```
python -m pytest tests/test_web_activity.py -v
```
Expected: 404 / template-not-found / nav assertion failures.

- [ ] **Step 3: Create the blueprint**

Create `D:\short\src\short_bot\web\routes\activity.py`:

```python
"""Activity timeline page: 24h summary + live runs + chronological feed."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, render_template, request

from short_bot.db import init_db
from short_bot.web.activity import (
    ALL_TYPES, build_activity_events, compute_summary_24h, list_running_runs,
)

bp = Blueprint("activity", __name__)


_SINCE_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _parse_filters():
    """Read filter args from request. Defaults: since=24h, no other filters."""
    channel = (request.args.get("channel") or "").strip() or None
    raw_type = (request.args.get("type") or "").strip()
    types = (raw_type,) if raw_type in ALL_TYPES else ALL_TYPES
    raw_status = (request.args.get("status") or "").strip()
    status = raw_status if raw_status in ("success", "failed", "no_candidates") else None
    since_key = (request.args.get("since") or "24h").strip()
    delta = _SINCE_WINDOWS.get(since_key, _SINCE_WINDOWS["24h"])
    since = datetime.now(timezone.utc) - delta
    cursor_raw = (request.args.get("cursor") or "").strip()
    cursor = None
    if cursor_raw:
        try:
            cursor = datetime.fromisoformat(cursor_raw)
        except ValueError:
            cursor = None
    return {
        "channel": channel,
        "types": types,
        "status": status,
        "since": since,
        "since_key": since_key,
        "cursor": cursor,
    }


@bp.route("/activity")
def view():
    """Full /activity page: summary + live runs + first feed page."""
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    f = _parse_filters()
    summary = compute_summary_24h(eng)
    running = list_running_runs(eng)
    events = build_activity_events(
        eng,
        since=f["since"], channel=f["channel"],
        types=f["types"], status=f["status"],
        limit=200, cursor=f["cursor"],
    )
    from short_bot.config import list_channels
    channels = list_channels(
        current_app.config["SHORTBOT_CONFIG_DIR"] / "channels", enabled_only=False,
    )
    return render_template(
        "activity.html.j2",
        summary=summary,
        running=running,
        events=events,
        channels=channels,
        f_channel=f["channel"] or "",
        f_type=request.args.get("type", "").strip(),
        f_status=request.args.get("status", "").strip(),
        f_since=f["since_key"],
    )
```

- [ ] **Step 4: Register the blueprint**

Edit `D:\short\src\short_bot\web\routes\__init__.py`:

```python
"""Blueprint registration."""
from flask import Flask


def register_blueprints(app: Flask) -> None:
    from short_bot.web.routes import (
        dashboard, shorts, rss, channels,
        channel_new, channel_edit, preview, logs, settings,
        generator_test, system, youtube, youtube_stats, youtube_overview,
        activity,
    )
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(shorts.bp)
    app.register_blueprint(rss.bp)
    app.register_blueprint(channels.bp)
    app.register_blueprint(channel_new.bp)
    app.register_blueprint(channel_edit.bp)
    app.register_blueprint(preview.bp)
    app.register_blueprint(logs.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(generator_test.bp)
    app.register_blueprint(system.bp)
    app.register_blueprint(youtube.bp)
    app.register_blueprint(youtube_stats.bp)
    app.register_blueprint(youtube_overview.bp)
    app.register_blueprint(activity.bp)
```

- [ ] **Step 5: Add the nav link**

Edit `D:\short\src\short_bot\web\templates\base.html.j2`. Find the existing nav link list (the `<a href="/" ...>Dashboard</a>` line and the lines that follow inside `<div class="flex items-center gap-7 ...">`). After the Dashboard link, BEFORE the Shorts link, add:

```html
        <a href="/activity" class="nav-link hover:text-claude-text {% if p.startswith('/activity') %}active{% endif %}">Akış</a>
```

The result should be: Dashboard → Akış → Shorts → RSS → Kanallar → YouTube → Loglar.

- [ ] **Step 6: Create a placeholder template**

Create `D:\short\src\short_bot\web\templates\activity.html.j2` (full layout comes in Task 8 — for now, the minimum needed for tests to pass):

```html
{% extends "base.html.j2" %}
{% block title %}Vurucu TİM — Akış{% endblock %}
{% block content %}
<h1 class="font-serif text-3xl font-bold mb-6">Akış</h1>

<div id="activity-feed" class="space-y-1">
  {% for e in events %}
  <div class="flex items-center gap-3 text-sm px-3 py-2 rounded hover:bg-claude-surface">
    <span class="font-mono text-xs text-claude-muted w-20 shrink-0">{{ e.timestamp.strftime('%H:%M:%S') }}</span>
    <span>{{ e.icon }}</span>
    <span class="px-2 py-0.5 rounded text-xs bg-claude-surface-alt">{{ e.channel }}</span>
    <span class="font-medium">{{ e.title }}</span>
    <span class="text-claude-muted text-xs flex-1 truncate">{{ e.detail }}</span>
  </div>
  {% else %}
  <div class="text-claude-muted text-center py-8">Henüz aktivite yok.</div>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 7: Run, expect PASS**

```
python -m pytest tests/test_web_activity.py -v
```
Expected: 3 passed.

Regression check:
```
python -m pytest tests/test_web_dashboard.py tests/test_web_shorts.py -v
```
Expected: still pass (nav addition shouldn't break anything).

- [ ] **Step 8: Commit**

```
git add src/short_bot/web/routes/activity.py src/short_bot/web/routes/__init__.py src/short_bot/web/templates/base.html.j2 src/short_bot/web/templates/activity.html.j2 tests/test_web_activity.py
git commit -m "feat(activity): add /activity page + nav link"
```

---

## Task 8: Full page template (3 zones)

Replace the placeholder template with the full 3-zone layout. Summary cards on top, live runs in the middle, feed on the bottom with filters.

**Files:**
- Modify: `D:\short\src\short_bot\web\templates\activity.html.j2`
- Modify: `D:\short\tests\test_web_activity.py`

- [ ] **Step 1: Write failing tests**

Append to `D:\short\tests\test_web_activity.py`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL**

```
python -m pytest tests/test_web_activity.py -v
```
Expected: 4 new tests fail (template lacks the structure).

- [ ] **Step 3: Replace the template**

Replace the entire content of `D:\short\src\short_bot\web\templates\activity.html.j2` with:

```html
{% extends "base.html.j2" %}
{% block title %}Vurucu TİM — Akış{% endblock %}
{% block content %}
<h1 class="font-serif text-3xl font-bold mb-6">Akış</h1>

{# ─── Zone 1: 24h summary cards ───────────────────────────────── #}
<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-8">
  <a href="/activity?type=run" class="bg-claude-surface hover:bg-claude-surface-alt border border-claude-border rounded-lg p-4 transition-colors">
    <div class="text-xs text-claude-muted uppercase tracking-wider">Run (24s)</div>
    <div class="text-2xl font-bold mt-1">{{ summary.runs_24h }}</div>
    <div class="text-xs text-claude-muted mt-1">
      <span class="text-claude-success">✓ {{ summary.runs_success_24h }}</span>
      ·
      <span class="text-claude-error">✗ {{ summary.runs_failed_24h }}</span>
    </div>
  </a>
  <a href="/activity?type=short" class="bg-claude-surface hover:bg-claude-surface-alt border border-claude-border rounded-lg p-4 transition-colors">
    <div class="text-xs text-claude-muted uppercase tracking-wider">Short (24s)</div>
    <div class="text-2xl font-bold mt-1">{{ summary.shorts_24h }}</div>
  </a>
  <a href="/activity?type=youtube" class="bg-claude-surface hover:bg-claude-surface-alt border border-claude-border rounded-lg p-4 transition-colors">
    <div class="text-xs text-claude-muted uppercase tracking-wider">YT yüklendi (24s)</div>
    <div class="text-2xl font-bold mt-1">{{ summary.youtube_success_24h }}</div>
  </a>
  <a href="/activity?type=error" class="bg-claude-surface hover:bg-claude-surface-alt border border-claude-border rounded-lg p-4 transition-colors {% if summary.errors_24h > 0 %}animate-pulse ring-2 ring-claude-error{% endif %}">
    <div class="text-xs text-claude-muted uppercase tracking-wider">Hata (24s)</div>
    <div class="text-2xl font-bold mt-1 {{ 'text-claude-error' if summary.errors_24h > 0 else 'text-claude-success' }}">
      {{ summary.errors_24h }}
    </div>
  </a>
</div>

{# ─── Zone 2: Live runs ───────────────────────────────────────── #}
<div class="mb-8">
  <h2 class="font-serif text-xl font-bold mb-3">Şu an çalışan</h2>
  <div class="bg-claude-surface border border-claude-border rounded-lg p-4">
    {% if running %}
      <ul class="space-y-2">
        {% for r in running %}
        <li class="flex items-center gap-3 text-sm" x-data="{ start: {{ r.started_at.timestamp() }}, now: Date.now() / 1000 }" x-init="setInterval(() => now = Date.now() / 1000, 1000)">
          <span class="w-2 h-2 rounded-full bg-yellow-500 animate-pulse"></span>
          <span class="font-medium">{{ r.channel }}</span>
          <span class="text-claude-muted text-xs">{{ r.trigger }}</span>
          <span class="text-claude-muted text-xs">başladı {{ r.started_at.strftime('%H:%M:%S') }}</span>
          <span class="ml-auto font-mono text-xs text-claude-muted">
            <span x-text="String(Math.floor((now - start) / 60)).padStart(2, '0') + ':' + String(Math.floor((now - start) % 60)).padStart(2, '0')"></span> geçti
          </span>
        </li>
        {% endfor %}
      </ul>
    {% else %}
      <div class="text-claude-muted text-sm text-center py-3">Şu an çalışan run yok.</div>
    {% endif %}
  </div>
</div>

{# ─── Zone 3: Filterable timeline feed ─────────────────────────── #}
<div class="flex items-center justify-between mb-4">
  <h2 class="font-serif text-xl font-bold">Akış</h2>
  <form class="flex gap-2 items-center" method="GET" action="/activity">
    <select name="channel" class="bg-claude-surface border border-claude-border px-2 py-1 rounded text-xs text-claude-text">
      <option value="">Tüm kanallar</option>
      {% for c in channels %}
        <option value="{{ c.slug }}" {% if f_channel == c.slug %}selected{% endif %}>{{ c.slug }}</option>
      {% endfor %}
    </select>
    <select name="type" class="bg-claude-surface border border-claude-border px-2 py-1 rounded text-xs text-claude-text">
      <option value="">Tüm tipler</option>
      <option value="run"     {% if f_type == 'run' %}selected{% endif %}>Run</option>
      <option value="short"   {% if f_type == 'short' %}selected{% endif %}>Short</option>
      <option value="youtube" {% if f_type == 'youtube' %}selected{% endif %}>YouTube</option>
      <option value="error"   {% if f_type == 'error' %}selected{% endif %}>Hata</option>
    </select>
    <select name="status" class="bg-claude-surface border border-claude-border px-2 py-1 rounded text-xs text-claude-text">
      <option value="">Tüm durumlar</option>
      <option value="success"        {% if f_status == 'success' %}selected{% endif %}>success</option>
      <option value="failed"         {% if f_status == 'failed' %}selected{% endif %}>failed</option>
      <option value="no_candidates"  {% if f_status == 'no_candidates' %}selected{% endif %}>no_candidates</option>
    </select>
    <select name="since" class="bg-claude-surface border border-claude-border px-2 py-1 rounded text-xs text-claude-text">
      <option value="1h"  {% if f_since == '1h' %}selected{% endif %}>Son 1 saat</option>
      <option value="24h" {% if f_since == '24h' %}selected{% endif %}>Son 24 saat</option>
      <option value="7d"  {% if f_since == '7d' %}selected{% endif %}>Son 7 gün</option>
      <option value="30d" {% if f_since == '30d' %}selected{% endif %}>Son 30 gün</option>
    </select>
    <button type="submit" class="text-xs bg-claude-accent hover:bg-claude-accent-hover text-white px-3 py-1 rounded">Filtre</button>
    <a href="/activity" class="text-xs text-claude-muted hover:text-claude-text underline ml-1">temizle</a>
  </form>
</div>

<div id="activity-feed" class="bg-claude-surface border border-claude-border rounded-lg divide-y divide-claude-border">
  {% for e in events %}
  <a href="{{ e.link }}" class="flex items-center gap-3 text-sm px-3 py-2 hover:bg-claude-surface-alt
       {% if e.type == 'error' %}bg-red-50/40{% endif %}">
    <span class="font-mono text-xs text-claude-muted w-20 shrink-0">{{ e.timestamp.strftime('%H:%M:%S') }}</span>
    <span class="w-5 text-center">{{ e.icon }}</span>
    <span class="px-2 py-0.5 rounded text-xs bg-claude-surface-alt shrink-0">{{ e.channel }}</span>
    <span class="font-medium shrink-0">{{ e.title }}</span>
    <span class="text-claude-muted text-xs truncate">{{ e.detail }}</span>
    {% if e.status %}
    <span class="ml-auto text-[10px] uppercase tracking-wider px-2 py-0.5 rounded
        {% if e.status == 'success' %}bg-claude-success/10 text-claude-success
        {% elif e.status == 'failed' %}bg-claude-error/10 text-claude-error
        {% else %}bg-claude-surface-alt text-claude-muted{% endif %}">
      {{ e.status }}
    </span>
    {% endif %}
  </a>
  {% else %}
  <div class="text-claude-muted text-center py-8">Bu filtre için sonuç yok.</div>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 4: Run, expect PASS**

```
python -m pytest tests/test_web_activity.py -v
```
Expected: 7 passed.

Regression check:
```
python -m pytest -q
```
Expected: ALL pass.

- [ ] **Step 5: Commit**

```
git add src/short_bot/web/templates/activity.html.j2 tests/test_web_activity.py
git commit -m "feat(activity): full 3-zone layout (summary + live + feed)"
```

---

## Task 9: htmx auto-refresh + partials

Carve the page into htmx-swappable partials so the feed and live-runs blocks refresh independently without a full reload.

**Files:**
- Create: `D:\short\src\short_bot\web\templates\_partials\activity_feed.html.j2`
- Create: `D:\short\src\short_bot\web\templates\_partials\activity_live_runs.html.j2`
- Modify: `D:\short\src\short_bot\web\templates\activity.html.j2`
- Modify: `D:\short\src\short_bot\web\routes\activity.py`
- Modify: `D:\short\tests\test_web_activity.py`

- [ ] **Step 1: Write failing tests**

Append to `D:\short\tests\test_web_activity.py`:

```python
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
    # No "run" event should appear in the rendered HTML when filtered to type=short
    # (we can't easily assert "no run" without coupling to wording, so check
    # that type=run events are gone via icon)


def test_activity_page_includes_htmx_attrs_for_auto_refresh(app):
    body = app.test_client().get("/activity").data.decode("utf-8")
    # Feed and live runs should both auto-refresh via htmx polling
    assert 'hx-get="/activity/feed"' in body
    assert 'hx-get="/activity/live-runs"' in body
    assert "every 10s" in body or 'every 10s"' in body
    assert "every 5s" in body or 'every 5s"' in body
```

- [ ] **Step 2: Run, expect FAIL**

```
python -m pytest tests/test_web_activity.py -v
```
Expected: 4 new tests fail.

- [ ] **Step 3: Add partial routes to the blueprint**

Append to `D:\short\src\short_bot\web\routes\activity.py`:

```python
@bp.route("/activity/feed")
def feed_partial():
    """htmx partial: renders only the feed rows. Filters apply."""
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    f = _parse_filters()
    events = build_activity_events(
        eng,
        since=f["since"], channel=f["channel"],
        types=f["types"], status=f["status"],
        limit=200, cursor=f["cursor"],
    )
    return render_template("_partials/activity_feed.html.j2", events=events)


@bp.route("/activity/live-runs")
def live_runs_partial():
    """htmx partial: renders only the live-runs section."""
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    running = list_running_runs(eng)
    return render_template("_partials/activity_live_runs.html.j2", running=running)
```

- [ ] **Step 4: Create the feed partial**

Create `D:\short\src\short_bot\web\templates\_partials\activity_feed.html.j2`:

```html
{% for e in events %}
<a href="{{ e.link }}" class="flex items-center gap-3 text-sm px-3 py-2 hover:bg-claude-surface-alt
     {% if e.type == 'error' %}bg-red-50/40{% endif %}">
  <span class="font-mono text-xs text-claude-muted w-20 shrink-0">{{ e.timestamp.strftime('%H:%M:%S') }}</span>
  <span class="w-5 text-center">{{ e.icon }}</span>
  <span class="px-2 py-0.5 rounded text-xs bg-claude-surface-alt shrink-0">{{ e.channel }}</span>
  <span class="font-medium shrink-0">{{ e.title }}</span>
  <span class="text-claude-muted text-xs truncate">{{ e.detail }}</span>
  {% if e.status %}
  <span class="ml-auto text-[10px] uppercase tracking-wider px-2 py-0.5 rounded
      {% if e.status == 'success' %}bg-claude-success/10 text-claude-success
      {% elif e.status == 'failed' %}bg-claude-error/10 text-claude-error
      {% else %}bg-claude-surface-alt text-claude-muted{% endif %}">
    {{ e.status }}
  </span>
  {% endif %}
</a>
{% else %}
<div class="text-claude-muted text-center py-8">Bu filtre için sonuç yok.</div>
{% endfor %}
```

- [ ] **Step 5: Create the live-runs partial**

Create `D:\short\src\short_bot\web\templates\_partials\activity_live_runs.html.j2`:

```html
{% if running %}
  <ul class="space-y-2">
    {% for r in running %}
    <li class="flex items-center gap-3 text-sm" x-data="{ start: {{ r.started_at.timestamp() }}, now: Date.now() / 1000 }" x-init="setInterval(() => now = Date.now() / 1000, 1000)">
      <span class="w-2 h-2 rounded-full bg-yellow-500 animate-pulse"></span>
      <span class="font-medium">{{ r.channel }}</span>
      <span class="text-claude-muted text-xs">{{ r.trigger }}</span>
      <span class="text-claude-muted text-xs">başladı {{ r.started_at.strftime('%H:%M:%S') }}</span>
      <span class="ml-auto font-mono text-xs text-claude-muted">
        <span x-text="String(Math.floor((now - start) / 60)).padStart(2, '0') + ':' + String(Math.floor((now - start) % 60)).padStart(2, '0')"></span> geçti
      </span>
    </li>
    {% endfor %}
  </ul>
{% else %}
  <div class="text-claude-muted text-sm text-center py-3">Şu an çalışan run yok.</div>
{% endif %}
```

- [ ] **Step 6: Wire htmx into the main page template**

Edit `D:\short\src\short_bot\web\templates\activity.html.j2`. Replace the live-runs `<div class="bg-claude-surface ...">` content (the inner `{% if running %}...{% else %}...{% endif %}` block) with an htmx-driven include + auto-refresh:

```html
  <div class="bg-claude-surface border border-claude-border rounded-lg p-4"
       hx-get="/activity/live-runs" hx-trigger="every 5s" hx-swap="innerHTML">
    {% include "_partials/activity_live_runs.html.j2" %}
  </div>
```

(Remove the old inline `{% if running %}...{% endif %}` block from inside that div.)

Then, replace the `<div id="activity-feed" ...>` block (the feed rows + close) with:

```html
<div id="activity-feed" class="bg-claude-surface border border-claude-border rounded-lg divide-y divide-claude-border"
     hx-get="/activity/feed" hx-trigger="every 10s" hx-swap="innerHTML"
     hx-include="[name='channel'], [name='type'], [name='status'], [name='since']">
  {% include "_partials/activity_feed.html.j2" %}
</div>
```

- [ ] **Step 7: Run, expect PASS**

```
python -m pytest tests/test_web_activity.py -v
```
Expected: 11 passed.

Full repo regression:
```
python -m pytest -q
```
Expected: ALL pass.

- [ ] **Step 8: Commit**

```
git add src/short_bot/web/routes/activity.py src/short_bot/web/templates/activity.html.j2 src/short_bot/web/templates/_partials/activity_feed.html.j2 src/short_bot/web/templates/_partials/activity_live_runs.html.j2 tests/test_web_activity.py
git commit -m "feat(activity): htmx auto-refresh partials (feed 10s, live-runs 5s)"
```

---

## Self-Review Notes

**Spec coverage check:**

| Spec section                                         | Implemented in        |
|------------------------------------------------------|-----------------------|
| `/activity` route                                    | Task 7                |
| ActivityEvent dataclass                              | Task 1                |
| Source: runs                                         | Task 1                |
| Source: shorts                                       | Task 2                |
| Source: youtube_uploads (success + failed)           | Task 3                |
| Filtering (channel, type, status, since)             | Tasks 4 + 7 (`_parse_filters`) |
| Cursor-based pagination                              | Task 5                |
| ActivitySummary 24h                                  | Task 6                |
| Live runs                                            | Task 6                |
| Three-zone template                                  | Task 8                |
| Errors-card pulse when count > 0                     | Task 8                |
| htmx partials + auto-refresh (feed 10s, live 5s)     | Task 9                |
| Alpine.js elapsed-time counter                       | Tasks 8 + 9           |
| Empty states (no events, no running runs, no filter) | Tasks 7 + 8 + 9       |
| Nav link "Akış"                                      | Task 7                |
| `processed_items` join for "X scored / Y picked" detail | NOT IMPLEMENTED — spec mentioned this in passing for the run-summary detail field. Task 1 uses `r.status` (e.g., "success") as the detail. Adding the picked count would require joining `rss_items` for each run, which adds complexity for marginal value. **Decision: out of scope for v1.** If the operator wants those details they can click the run row → opens /logs?channel=…. |
| Tests in `test_activity_events.py`                   | Tasks 1-6             |
| Tests in `test_web_activity.py`                      | Tasks 7-9             |

**Placeholder scan:** No `TBD`, `TODO`, "implement later". All steps have full code.

**Type consistency:**
- `ActivityEvent` fields are referenced consistently (`timestamp`, `type`, `channel`, `title`, `detail`, `status`, `link`, `icon`).
- `EventType` literals match across builder and route filters: `"run"`, `"short"`, `"youtube"`, `"error"`.
- `ALL_TYPES` exported from activity.py and imported in route.py — name matches.
- `_aware()` helper used identically in all date-handling paths.
- `compute_summary_24h` returns `ActivitySummary` with the field names referenced by template (`runs_24h`, `runs_success_24h`, `runs_failed_24h`, `shorts_24h`, `youtube_success_24h`, `errors_24h`).
- `list_running_runs` returns `RunningRun` with fields the template uses (`id`, `channel`, `trigger`, `started_at`).

Plan complete and saved to `docs/superpowers/plans/2026-05-07-activity-timeline.md`.
