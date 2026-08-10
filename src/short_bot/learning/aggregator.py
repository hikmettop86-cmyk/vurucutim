"""Per-channel performance insights from YouTube stats history.

Public API:
    compute_channel_insights(eng, channel, *, lookback_days=30) -> dict
    refresh_all_channels(eng, *, lookback_days=30) -> dict[str, int]

Output dict shape (kept stable so the template + scorer-injection layer
can rely on it):

    {
      "lookback_days": 30,
      "sample_size": 11,
      "stats_age_warning": False,
      "top_categories": [
        {"category": "Dünya", "n": 4, "avg_views": 1625.0,
         "median_views": 1618, "avg_watch_pct": 0.0, "total_views": 6501},
        ...
      ],
      "top_moods": [
        {"mood": "breaking", "n": 14, "avg_views": 1703.0, "avg_watch_pct": 22.6},
        ...
      ],
      "top_view_examples": [
        {"short_id": 17, "title": "...", "views": 8225, "watch_pct": 0,
         "category": "Siyaset", "mood": "breaking", "age_days": 1},
        ...
      ],
      "watch_pct_leaders": [
        {"short_id": 3, "title": "...", "views": 2764, "watch_pct": 183.3,
         "category": "Gündem", "mood": "breaking"},
        ...
      ],
      "bottom_examples": [
        {"short_id": 9, "title": "...", "views": 0, "category": "...",
         "age_days": 0},
        ...
      ]
    }

`stats_age_warning` is True when no short has a usable stats snapshot —
typically right after the first upload, before YT Analytics has caught up.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.engine import Engine

from short_bot.db import shorts, youtube_uploads, youtube_video_stats
from short_bot.topic_taxonomy import normalize_category


_MIN_VIEWS_FOR_WATCH_LEADERS = 5      # ignore noise from <5-view videos
_TOP_CATEGORIES = 5
_TOP_VIEW_EXAMPLES = 8
_WATCH_LEADERS = 5
_BOTTOM_EXAMPLES = 5
_MIN_CATEGORY_SAMPLES = 2             # categories with n=1 are stripped out


def compute_channel_insights(
    eng: Engine, channel: str, *, lookback_days: int = 30,
) -> dict[str, Any]:
    """Compute the insights dict for `channel`. Cheap (single join query).

    Includes only uploads from the past `lookback_days`. Recent uploads with
    no stats yet are counted in `_meta.upload_count` (set by caller) but
    excluded from per-category averages.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    # Single query: every upload + its latest stats snapshot
    with eng.connect() as conn:
        rows = conn.execute(
            select(
                shorts.c.id.label("short_id"),
                shorts.c.title.label("title"),
                shorts.c.duration_s.label("duration_s"),
                shorts.c.script_json.label("script_json"),
                shorts.c.created_at.label("created_at"),
                youtube_uploads.c.video_id.label("video_id"),
                youtube_uploads.c.uploaded_at.label("uploaded_at"),
            )
            .select_from(
                shorts.join(youtube_uploads, youtube_uploads.c.short_id == shorts.c.id)
            )
            .where(shorts.c.channel == channel)
            # deleted_at'e BAKILMAZ: panelin "sil" düğmesi videoyu YouTube'dan
            # kaldırmaz, sadece listeden gizler. Yayındaki video izlenmeye
            # devam ettiği sürece performans verisi geçerlidir. Bu filtre
            # yüzünden panelde "tümünü sil" yapılan kanallarda sample_size 0'a
            # düşüyor ve scorer aylarca hiç geri besleme almıyordu (galatasaray:
            # 695 short'un 694'ü deleted_at'liydi). status=="success" koşulu
            # zaten yalnız gerçekten yayınlanmışları bırakıyor.
            .where(youtube_uploads.c.status == "success")
            .where(youtube_uploads.c.uploaded_at >= cutoff)
        ).all()

    # Pull latest stats row per video_id (1 query per channel, small)
    stats_by_vid: dict[str, dict[str, Any]] = {}
    if rows:
        vids = [r.video_id for r in rows if r.video_id]
        if vids:
            with eng.connect() as conn:
                srows = conn.execute(
                    select(
                        youtube_video_stats.c.video_id,
                        youtube_video_stats.c.snapshot_date,
                        youtube_video_stats.c.views,
                        youtube_video_stats.c.likes,
                        youtube_video_stats.c.comments,
                        youtube_video_stats.c.avg_view_duration_s,
                        youtube_video_stats.c.watch_time_min,
                    )
                    .where(youtube_video_stats.c.video_id.in_(vids))
                ).all()
            # views/likes/comments KÜMÜLATİF: son snapshot doğru değeri taşır.
            # avg_view_duration_s / watch_time_min ise PENCERE-bazlı: video
            # sönünce pencerede 1-2 izlenme kalıyor ve biri döngüde bırakırsa
            # ortalama uçuyor (gerçek kayıt: 6sn'lik short'ta 198s ortalama =
            # %3300 watch, ama o pencerede yalnız ~1.8 izlenme vardı — bu
            # scorer'a "en iyi örnek" diye gidiyordu). Bu yüzden izlenme
            # metrikleri videonun EN YOĞUN izlendiği pencereden alınır.
            peak_window: dict[str, dict[str, float]] = {}
            for s in srows:
                prev = stats_by_vid.get(s.video_id)
                if prev is None or s.snapshot_date > prev["snapshot_date"]:
                    stats_by_vid[s.video_id] = {
                        "snapshot_date": s.snapshot_date,
                        "views": int(s.views or 0),
                        "likes": int(s.likes or 0),
                        "comments": int(s.comments or 0),
                        "avg_view_duration_s": float(s.avg_view_duration_s or 0.0),
                        "watch_time_min": float(s.watch_time_min or 0.0),
                    }
                watch_min = float(s.watch_time_min or 0.0)
                peak = peak_window.get(s.video_id)
                if peak is None or watch_min > peak["watch_time_min"]:
                    peak_window[s.video_id] = {
                        "watch_time_min": watch_min,
                        "avg_view_duration_s": float(s.avg_view_duration_s or 0.0),
                    }
            for vid, peak in peak_window.items():
                if vid in stats_by_vid:
                    stats_by_vid[vid]["avg_view_duration_s"] = peak["avg_view_duration_s"]
                    stats_by_vid[vid]["watch_time_min"] = peak["watch_time_min"]

    enriched: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for r in rows:
        try:
            sc = json.loads(r.script_json or "{}")
        except (TypeError, ValueError):
            sc = {}

        stats = stats_by_vid.get(r.video_id, {})
        views = stats.get("views", 0)
        duration_s = int(r.duration_s or 6)
        avg_dur = stats.get("avg_view_duration_s", 0.0)
        # Watch% can exceed 100 for Shorts because loops count toward
        # averageViewDuration — that's a STRONG positive signal (viewer
        # rewatched), not a bug.
        watch_pct = (avg_dur / duration_s) * 100.0 if duration_s > 0 else 0.0
        eng_rate = (
            (stats.get("likes", 0) + stats.get("comments", 0)) / views * 100.0
            if views > 0 else 0.0
        )
        uploaded = r.uploaded_at
        if uploaded is not None and uploaded.tzinfo is None:
            uploaded = uploaded.replace(tzinfo=timezone.utc)
        age_days = (now - uploaded).days if uploaded else 0

        enriched.append({
            "short_id": int(r.short_id),
            "title": r.title or "",
            "video_id": r.video_id or "",
            "views": views,
            "watch_pct": watch_pct,
            "eng_rate": eng_rate,
            "age_days": age_days,
            "category": normalize_category(sc.get("category")),
            "mood": (sc.get("mood") or "?").strip() or "?",
            "has_stats": r.video_id in stats_by_vid,
        })

    # === Aggregations ======================================================
    sample_size = sum(1 for e in enriched if e["has_stats"])
    stats_age_warning = bool(enriched) and sample_size == 0

    # By category (only those with >= _MIN_CATEGORY_SAMPLES samples)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for e in enriched:
        if e["has_stats"]:
            by_cat[e["category"]].append(e)
    top_categories = []
    for cat, items in by_cat.items():
        if len(items) < _MIN_CATEGORY_SAMPLES:
            continue
        n = len(items)
        sv = sorted(x["views"] for x in items)
        top_categories.append({
            "category": cat, "n": n,
            "avg_views": sum(x["views"] for x in items) / n,
            "median_views": sv[n // 2],
            "avg_watch_pct": sum(x["watch_pct"] for x in items) / n,
            "total_views": sum(x["views"] for x in items),
        })
    # ORTALAMAYA göre sırala, toplama göre değil. Toplam sıralaması en ÇOK
    # ÜRETİLEN konuyu "en iyi" gibi gösteriyordu ve scorer'a tam ters sinyal
    # gidiyordu: galatasaray'da transfer-gelen (n=98, medyan 43.957) hint'in
    # başındaydı, avrupa-kura (n=2, medyan 97.927 — kanalın en iyisi) ilk 3'e
    # bile giremiyordu. Bu, doygunluk döngüsünü besliyor: çok üret → hint'te
    # üste çık → daha çok üretil. n değeri hint'te gösterildiği için küçük
    # örneklemi model yine de tartabilir.
    top_categories.sort(key=lambda x: x["avg_views"], reverse=True)
    top_categories = top_categories[:_TOP_CATEGORIES]

    # By mood (include all moods; usually <=3 anyway)
    by_mood: dict[str, list[dict]] = defaultdict(list)
    for e in enriched:
        if e["has_stats"]:
            by_mood[e["mood"]].append(e)
    top_moods = []
    for mood, items in by_mood.items():
        n = len(items)
        top_moods.append({
            "mood": mood, "n": n,
            "avg_views": sum(x["views"] for x in items) / n,
            "avg_watch_pct": sum(x["watch_pct"] for x in items) / n,
        })
    top_moods.sort(key=lambda x: x["avg_views"], reverse=True)

    # Top examples
    with_stats = [e for e in enriched if e["has_stats"]]
    top_view_examples = sorted(with_stats, key=lambda x: x["views"],
                                reverse=True)[:_TOP_VIEW_EXAMPLES]
    bottom_examples = sorted(with_stats, key=lambda x: x["views"])[:_BOTTOM_EXAMPLES]

    # Watch leaders (require minimum views to avoid noise)
    watch_pct_leaders = [
        e for e in with_stats if e["views"] >= _MIN_VIEWS_FOR_WATCH_LEADERS
    ]
    watch_pct_leaders.sort(key=lambda x: x["watch_pct"], reverse=True)
    watch_pct_leaders = watch_pct_leaders[:_WATCH_LEADERS]

    return {
        "lookback_days": lookback_days,
        "sample_size": sample_size,
        "upload_count": len(enriched),
        "stats_age_warning": stats_age_warning,
        "top_categories": top_categories,
        "top_moods": top_moods,
        "top_view_examples": top_view_examples,
        "watch_pct_leaders": watch_pct_leaders,
        "bottom_examples": bottom_examples,
    }


def refresh_all_channels(eng: Engine, *, lookback_days: int = 30) -> dict[str, int]:
    """Recompute insights for every channel that has uploads + persist to DB.
    Returns {channel: sample_size}."""
    from short_bot.db import load_channels_with_uploads, upsert_channel_insights

    results: dict[str, int] = {}
    for channel in load_channels_with_uploads(eng):
        insights = compute_channel_insights(eng, channel, lookback_days=lookback_days)
        upsert_channel_insights(
            eng, channel=channel,
            sample_size=insights["sample_size"],
            data_json=json.dumps(insights, ensure_ascii=False),
        )
        results[channel] = insights["sample_size"]
    return results
