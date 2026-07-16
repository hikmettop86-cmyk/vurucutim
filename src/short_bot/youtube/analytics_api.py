"""youtubeAnalytics API v2 — daily metrics with 48-72h delay."""
from __future__ import annotations

from datetime import date

from googleapiclient.discovery import build


# subscribersGained + averageViewPercentage: beğeni/abone teşhisi (2026-07-16)
# gösterdi ki dönüşüm video başına 7x oynuyor — hangi videonun abone getirdiğini
# görmeden içerik kararı alınamaz. Not: averageViewPercentage Shorts'ta %100'ü
# aşabilir (loop izlenmeleri sayılır) — bu hata değil, güçlü pozitif sinyal.
_METRICS = ("views,estimatedMinutesWatched,averageViewDuration,"
            "subscribersGained,averageViewPercentage")


def fetch_video_analytics(credentials, *, start_date: date, end_date: date,
                          video_ids: list[str]) -> dict[str, dict]:
    """Per-video aggregated metrics for the date window.

    Returns {video_id: {watch_time_min, avg_view_duration_s, views_in_window,
    subscribers_gained, avg_view_percentage}}.
    """
    if not video_ids:
        return {}
    yta = build("youtubeAnalytics", "v2", credentials=credentials)
    filter_str = "video==" + ",".join(video_ids)
    resp = yta.reports().query(
        ids="channel==MINE",
        startDate=start_date.isoformat(),
        endDate=end_date.isoformat(),
        metrics=_METRICS,
        dimensions="video",
        filters=filter_str,
    ).execute()

    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    rows = resp.get("rows", [])
    if not rows:
        return {}

    idx = {name: i for i, name in enumerate(headers)}
    out: dict[str, dict] = {}
    for row in rows:
        vid = row[idx["video"]]
        out[vid] = {
            "watch_time_min": float(row[idx["estimatedMinutesWatched"]])
                              if "estimatedMinutesWatched" in idx else 0.0,
            "avg_view_duration_s": float(row[idx["averageViewDuration"]])
                                    if "averageViewDuration" in idx else 0.0,
            "views_in_window": int(row[idx["views"]])
                                if "views" in idx else 0,
            "subscribers_gained": int(row[idx["subscribersGained"]])
                                   if "subscribersGained" in idx else 0,
            "avg_view_percentage": float(row[idx["averageViewPercentage"]])
                                    if "averageViewPercentage" in idx else 0.0,
        }
    return out
