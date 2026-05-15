"""Google Daily Trends RSS poller.

Endpoint: https://trends.google.com/trending/rss?geo=XX

(The legacy path /trends/trendingsearches/daily/rss was retired by Google in
2024 and now serves 404. The "Trending Now" endpoint above is its successor
and exposes the same item-with-title shape feedparser already understands.)

Returns up to ~20 trending search terms per region. Some regions sometimes
serve an empty feed; treat that as "no trends right now" (caller falls back
to score-only). Network errors return [] -- never raise.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import requests

from short_bot.trends import TrendItem

logger = logging.getLogger(__name__)

_BASE_URL = "https://trends.google.com/trending/rss"
# Google's RSS endpoint refuses non-browser UAs with 403 in some regions.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 short-bot/0.1")


def fetch_google_daily_trends(
    region: str,
    *,
    timeout_s: int = 10,
    max_results: int = 20,
) -> list[TrendItem]:
    """Fetch top trending searches for `region`. Empty list on any error.

    `region` is an ISO 3166-1 alpha-2 code (TR, US, DE, ES, FR).
    """
    url = f"{_BASE_URL}?geo={region}"
    try:
        r = requests.get(url, timeout=timeout_s, headers={"User-Agent": _UA})
    except requests.RequestException as e:
        logger.warning(f"google_daily fetch request failed ({region}): {e}")
        return []

    if r.status_code != 200:
        logger.warning(
            f"google_daily HTTP {r.status_code} for region={region}: {r.text[:200]}"
        )
        return []

    parsed = feedparser.parse(r.content)
    now = datetime.now(timezone.utc)
    out: list[TrendItem] = []
    for rank, entry in enumerate(parsed.entries[:max_results], start=1):
        term = (entry.get("title") or "").strip()
        if not term:
            continue
        out.append(TrendItem(
            term=term,
            source="google_daily",
            region=region.upper(),
            rank=rank,
            score=_rank_score(rank, max_results),
            fetched_at=now,
        ))
    if not out:
        logger.info(f"google_daily empty feed for region={region}")
    return out


def _rank_score(rank: int, n: int) -> float:
    """Linear rank -> 0..1 normalization. rank=1 -> ~1.0, rank=n -> close to 0."""
    if n <= 1:
        return 1.0
    return max(0.0, 1.0 - (rank - 1) / n)
