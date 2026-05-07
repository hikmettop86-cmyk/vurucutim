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

from short_bot.db import runs, shorts as shorts_table, youtube_uploads


EventType = Literal["run", "short", "youtube", "error"]
EventStatus = Literal["success", "failed", "no_candidates", "running"]

ALL_TYPES: tuple[EventType, ...] = ("run", "short", "youtube", "error")


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
_SHORT_ICON = "✓"
_YOUTUBE_ICON = "▶"


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
