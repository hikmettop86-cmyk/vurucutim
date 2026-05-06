"""YouTube Data API v3 wrappers — videos.list and channels.list (cumulative stats)."""
from __future__ import annotations

from googleapiclient.discovery import build


_BATCH_SIZE = 50


def fetch_video_stats_batch(credentials, video_ids: list[str]) -> dict[str, dict]:
    """Return {video_id: {views, likes, comments}} for each id.

    Splits into 50-id batches (API cap). Missing videos (deleted, private)
    are absent from the result dict.
    """
    if not video_ids:
        return {}
    youtube = build("youtube", "v3", credentials=credentials)
    out: dict[str, dict] = {}
    for i in range(0, len(video_ids), _BATCH_SIZE):
        chunk = video_ids[i:i + _BATCH_SIZE]
        resp = youtube.videos().list(
            part="statistics", id=",".join(chunk),
        ).execute()
        for item in resp.get("items", []):
            stats = item.get("statistics", {})
            out[item["id"]] = {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
            }
    return out


def fetch_channel_stats(credentials) -> dict | None:
    """channels.list(mine=True) — subscriber + total view count."""
    youtube = build("youtube", "v3", credentials=credentials)
    resp = youtube.channels().list(
        part="statistics,snippet", mine=True,
    ).execute()
    items = resp.get("items", [])
    if not items:
        return None
    item = items[0]
    stats = item.get("statistics", {})
    return {
        "channel_id": item["id"],
        "subscribers": int(stats.get("subscriberCount", 0)),
        "total_views": int(stats.get("viewCount", 0)),
    }
