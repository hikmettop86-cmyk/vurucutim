"""YouTube Trending fetcher via videos.list(chart=mostPopular).

Uses an API key (no OAuth required for this endpoint). Quota cost: 1 unit per
call. Returns up to 50 trending video titles per region.

Setup: user needs a Google Cloud API key with YouTube Data API v3 enabled.
Stored in secrets.yaml under `youtube_api_key`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from short_bot.trends import TrendItem

logger = logging.getLogger(__name__)


def fetch_youtube_trending(
    api_key: str,
    *,
    region: str,
    max_results: int = 25,
    category_id: str | None = None,
) -> list[TrendItem]:
    """Fetch top trending video titles for `region`. Empty on any error.

    region: ISO 3166-1 alpha-2 (TR, US, DE, ...)
    category_id: optional YouTube videoCategoryId (e.g., '25'=News, '17'=Sports).
                  None = broad trending across all categories.
    """
    if not api_key:
        return []

    try:
        yt = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        params = {
            "part": "snippet",
            "chart": "mostPopular",
            "regionCode": region.upper(),
            "maxResults": min(max_results, 50),
        }
        if category_id:
            params["videoCategoryId"] = category_id
        resp = yt.videos().list(**params).execute()
    except HttpError as e:
        logger.warning(f"youtube trending HttpError region={region}: {e}")
        return []
    except Exception as e:  # broad: network / discovery build / unexpected
        logger.warning(f"youtube trending error region={region}: {e}")
        return []

    now = datetime.now(timezone.utc)
    items_in = resp.get("items", [])
    out: list[TrendItem] = []
    for rank, video in enumerate(items_in, start=1):
        title = (video.get("snippet", {}).get("title") or "").strip()
        if not title:
            continue
        out.append(TrendItem(
            term=title,
            source="youtube",
            region=region.upper(),
            rank=rank,
            score=_rank_score(rank, len(items_in)),
            fetched_at=now,
        ))
    return out


def _rank_score(rank: int, n: int) -> float:
    if n <= 1:
        return 1.0
    return max(0.0, 1.0 - (rank - 1) / n)
