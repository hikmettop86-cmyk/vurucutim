"""Aggregate trends from multiple sources + JSON cache I/O.

Public surface:
- refresh_trends(region, sources, secrets, cache_dir) -> TrendCache
- load_trends_cache(region, cache_dir) -> TrendCache | None
- get_or_refresh(region, max_age_minutes, ...) -> TrendCache | None

Network failures are absorbed: a missing source contributes [] to the
aggregate. If all sources fail, the resulting TrendCache has items=[] and
the caller should fall back to score-only.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from short_bot.trends import TrendCache, TrendItem
from short_bot.trends.google_daily import fetch_google_daily_trends
from short_bot.trends.youtube_trending import fetch_youtube_trending

logger = logging.getLogger(__name__)


def refresh_trends(
    region: str,
    *,
    sources: list[str],
    youtube_api_key: str = "",
    cache_dir: Path | None = None,
    youtube_category_id: str | None = None,
) -> TrendCache:
    """Fetch trends from every requested source, dedup, persist to cache."""
    region = region.upper()
    items: list[TrendItem] = []

    if "google_daily" in sources:
        items.extend(fetch_google_daily_trends(region))

    if "youtube" in sources:
        if youtube_api_key:
            items.extend(fetch_youtube_trending(
                youtube_api_key, region=region,
                category_id=youtube_category_id,
            ))
        else:
            logger.info(
                "youtube source requested but no api key configured -- skipping"
            )

    # Dedup by normalized term; keep highest-score copy across sources
    from short_bot.trends.matcher import normalize_text
    dedup: dict[str, TrendItem] = {}
    for it in items:
        key = normalize_text(it.term)
        if not key:
            continue
        prev = dedup.get(key)
        if prev is None or it.score > prev.score:
            dedup[key] = it

    cache = TrendCache(
        region=region,
        fetched_at=datetime.now(timezone.utc),
        items=sorted(dedup.values(), key=lambda x: x.score, reverse=True),
        sources=list(sources),
    )

    if cache_dir is not None:
        _persist(cache, cache_dir)
    return cache


def load_trends_cache(region: str, cache_dir: Path) -> TrendCache | None:
    """Load cached trends for region. Returns None on missing/invalid file."""
    path = Path(cache_dir) / f"{region.lower()}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"trends cache parse error for {region}: {e}")
        return None
    return _deserialize(raw)


def get_or_refresh(
    region: str,
    *,
    sources: list[str],
    youtube_api_key: str,
    cache_dir: Path,
    max_age_minutes: float = 90.0,
    youtube_category_id: str | None = None,
) -> TrendCache | None:
    """Return fresh cache if available, else refresh inline.

    Falls back to stale cache if refresh produces no items (network down).
    Returns None only when there's no cache AND refresh produced nothing.
    """
    cached = load_trends_cache(region, cache_dir)
    if cached is not None and cached.is_fresh(max_age_minutes):
        return cached

    fresh = refresh_trends(
        region, sources=sources, youtube_api_key=youtube_api_key,
        cache_dir=cache_dir, youtube_category_id=youtube_category_id,
    )
    if fresh.items:
        return fresh
    # All sources failed (empty fresh). Prefer stale cache to nothing.
    return cached


def _persist(cache: TrendCache, cache_dir: Path) -> None:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{cache.region.lower()}.json"
    path.write_text(json.dumps(_serialize(cache), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _serialize(cache: TrendCache) -> dict:
    return {
        "region": cache.region,
        "fetched_at": cache.fetched_at.isoformat(),
        "sources": list(cache.sources),
        "items": [
            {**asdict(i), "fetched_at": i.fetched_at.isoformat()}
            for i in cache.items
        ],
    }


def _deserialize(raw: dict) -> TrendCache | None:
    try:
        items = []
        for d in raw.get("items", []):
            items.append(TrendItem(
                term=d["term"],
                source=d["source"],
                region=d["region"],
                rank=int(d["rank"]),
                score=float(d["score"]),
                fetched_at=datetime.fromisoformat(d["fetched_at"]),
            ))
        return TrendCache(
            region=raw["region"],
            fetched_at=datetime.fromisoformat(raw["fetched_at"]),
            items=items,
            sources=list(raw.get("sources", [])),
        )
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"trends cache deserialize error: {e}")
        return None
