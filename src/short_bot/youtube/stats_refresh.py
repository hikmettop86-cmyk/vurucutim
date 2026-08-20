"""Per-channel daily stats refresh — Data API + Analytics API + DB upserts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from short_bot.db import (
    upsert_video_stats, upsert_channel_stats, incr_quota,
    youtube_uploads, shorts as _shorts_t,
)
from short_bot.youtube import auth as _yt_auth
from short_bot.youtube.data_api import fetch_video_stats_batch, fetch_channel_stats
from short_bot.youtube.analytics_api import fetch_video_analytics


_QUOTA_CHANNELS_LIST = 1
_QUOTA_VIDEOS_LIST_BATCH = 1
_QUOTA_ANALYTICS_REPORT = 5


@dataclass(frozen=True)
class RefreshResult:
    channel_slug: str
    video_count: int
    channel_updated: bool
    skipped_reason: str = ""


def refresh_channel_stats(*, eng, channel_slug: str, yt_creds_root: Path,
                          video_lookback_days: int = 30,
                          creds_slug: str | None = None) -> RefreshResult:
    """Refresh stats for one connected channel.

    ``creds_slug``: kimliği başka bir kanaldan ödünç alan kanallar için
    (youtube.credentials_from). Verilmezse kanalın kendi slug'ı kullanılır."""
    creds = _yt_auth.load_credentials(yt_creds_root, creds_slug or channel_slug)
    if creds is None:
        return RefreshResult(channel_slug, 0, False, "no credentials")

    today = date.today()

    channel_data = fetch_channel_stats(creds)
    incr_quota(eng, channel=channel_slug, units=_QUOTA_CHANNELS_LIST)
    channel_updated = False
    if channel_data is not None:
        upsert_channel_stats(
            eng, channel=channel_slug, snapshot_date=today,
            subscribers=channel_data["subscribers"],
            total_views=channel_data["total_views"],
        )
        channel_updated = True

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=video_lookback_days)
    with eng.connect() as conn:
        rows = list(conn.execute(
            select(youtube_uploads.c.video_id, youtube_uploads.c.short_id)
            .where(youtube_uploads.c.status == "success")
            .where(youtube_uploads.c.uploaded_at >= cutoff_dt)
        ))
    video_ids: list[str] = []
    if rows:
        with eng.connect() as conn:
            for r in rows:
                row = conn.execute(
                    select(_shorts_t.c.channel)
                    .where(_shorts_t.c.id == r.short_id)
                ).first()
                if row and row.channel == channel_slug and r.video_id:
                    video_ids.append(r.video_id)

    if not video_ids:
        return RefreshResult(channel_slug, 0, channel_updated)

    cum = fetch_video_stats_batch(creds, video_ids=video_ids)
    incr_quota(eng, channel=channel_slug,
                units=_QUOTA_VIDEOS_LIST_BATCH * ((len(video_ids) + 49) // 50))

    end = today - timedelta(days=3)
    start = end - timedelta(days=7)
    analytics = fetch_video_analytics(
        creds, start_date=start, end_date=end, video_ids=video_ids,
    )
    incr_quota(eng, channel=channel_slug, units=_QUOTA_ANALYTICS_REPORT)

    for vid in video_ids:
        c = cum.get(vid, {"views": 0, "likes": 0, "comments": 0})
        a = analytics.get(vid, {"watch_time_min": 0.0, "avg_view_duration_s": 0.0})
        upsert_video_stats(
            eng, video_id=vid, snapshot_date=today,
            views=c["views"], likes=c["likes"], comments=c["comments"],
            watch_time_min=a["watch_time_min"],
            avg_view_duration_s=a["avg_view_duration_s"],
            subscribers_gained=a.get("subscribers_gained", 0),
            avg_view_percentage=a.get("avg_view_percentage", 0.0),
        )

    return RefreshResult(channel_slug, len(video_ids), channel_updated)
