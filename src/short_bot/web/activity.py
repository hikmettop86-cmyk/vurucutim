"""Activity event builder.

Pure module. Reads from `runs`, `shorts`, `youtube_uploads` tables and
returns a unified, time-sorted list of ActivityEvent records for the
operator's /activity page. No Flask dependencies — testable in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select
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
    """Üretilen her video için bir olay — KARAR VERİLMİŞ olanlar DAHİL.

    ``deleted_at`` çöp değil, operatörün KARARIDIR (bkz. ``dashboard_stats``
    başlığı): beğendiğini YÜKLEYİP listeden siler. ``deleted_at IS NULL``
    süzen bir akış «üretimi» değil «gelen kutusunu» gösterir ve sayfa kendi
    kendisiyle çelişir — ölçüldü (2026-08-23): başlıkta 66 koşu ✓, 26 YouTube
    yüklemesi ve 1 video yazıyordu. 1 videodan 26 yükleme çıkamaz.
    """
    out: list[ActivityEvent] = []
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts_table)
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
        # `deleted_at` süzülmez: koşu ve yükleme sayaçları da süzmüyor,
        # süzen tek sayaç sayfayı çelişkiye düşürüyordu (bkz.
        # `_build_short_events` gerekçesi).
        shorts_count = conn.execute(
            select(func.count()).select_from(shorts_table)
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
    """Runs with ended_at IS NULL ordered by started_at DESC.

    Bounded to the last 60 minutes to match cleanup_zombie_runs behavior at
    app startup — older 'running' rows are abandoned never-finished runs and
    shouldn't pile up in the live panel.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)
    with eng.connect() as conn:
        rows = conn.execute(
            select(runs.c.id, runs.c.channel, runs.c.trigger, runs.c.started_at)
            .where(runs.c.ended_at.is_(None))
            .where(runs.c.started_at >= cutoff)
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
