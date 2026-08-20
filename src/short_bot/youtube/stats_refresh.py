"""Per-channel daily stats refresh — Data API + Analytics API + DB upserts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from short_bot.db import (
    upsert_video_stats, upsert_channel_stats, incr_quota, upsert_search_terms,
    kv_touch, youtube_uploads, shorts as _shorts_t,
)
from short_bot.youtube import auth as _yt_auth
from short_bot.youtube.data_api import fetch_video_stats_batch, fetch_channel_stats
from short_bot.youtube.analytics_api import (
    fetch_search_terms, fetch_traffic_sources, fetch_video_analytics,
)


_QUOTA_CHANNELS_LIST = 1
_QUOTA_VIDEOS_LIST_BATCH = 1
_QUOTA_ANALYTICS_REPORT = 5


@dataclass(frozen=True)
class RefreshResult:
    channel_slug: str
    video_count: int
    channel_updated: bool
    skipped_reason: str = ""
    search_terms: int = 0


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

    # ARAMA SÖZLÜĞÜ: bizi bulan gerçek sorgular. Video listesinden ÖNCE ve ondan
    # bağımsız tazelenir — uzun süre video yüklemeyen bir kanalın eski videoları
    # hâlâ aramadan izlenme alıyor (ölçüm: 60+ günlük videolarda arama payı %17,3)
    # ve o sözlük yeni videoların başlığını yazarken de geçerli.
    # Her hata yutulur: sözlük bir İYİLEŞTİRME girdisidir, istatistik tazelemenin
    # şartı değil.
    search_terms_written = 0
    try:
        _end = today - timedelta(days=3)      # Analytics 48-72 saat gecikmeli
        terms = fetch_search_terms(creds, start_date=_end - timedelta(days=27),
                                   end_date=_end, limit=25)
        incr_quota(eng, channel=channel_slug, units=_QUOTA_ANALYTICS_REPORT)
        search_terms_written = upsert_search_terms(
            eng, channel=channel_slug, terms=terms, window_end=_end)
    except Exception:  # noqa: BLE001 — sözlük yoksa metadata Trends ile yetinir
        pass

    # TRAFİK DAĞILIMI: aramanın payı. Tek satırlık kv kaydı — pano değil, ÖLÇÜ.
    # Metadata'yı gerçek sorgulara göre yazmanın (Aşama 1) işe yarayıp yaramadığı
    # ancak bu oran zaman içinde izlenirse anlaşılır. Başlangıç ölçümü
    # (2026-08-20): dört kanalda da arama %2,2–2,9.
    try:
        import json as _json
        _end = today - timedelta(days=3)
        mix = fetch_traffic_sources(creds, start_date=_end - timedelta(days=27),
                                    end_date=_end)
        incr_quota(eng, channel=channel_slug, units=_QUOTA_ANALYTICS_REPORT)
        total = sum(v.get("views", 0) for v in mix.values())
        if total:
            kv_touch(eng, f"traffic:{channel_slug}", _json.dumps({
                "total": total,
                "search_pct": round(100 * mix.get("YT_SEARCH", {}).get("views", 0) / total, 1),
                "feed_pct": round(100 * mix.get("SHORTS", {}).get("views", 0) / total, 1),
                "window_end": _end.isoformat(),
            }))
    except Exception:  # noqa: BLE001 — ölçü yoksa üretim etkilenmez
        pass

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
        return RefreshResult(channel_slug, 0, channel_updated,
                             search_terms=search_terms_written)

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

    return RefreshResult(channel_slug, len(video_ids), channel_updated,
                         search_terms=search_terms_written)
