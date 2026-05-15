"""Trend detection: Google Daily Trends + YouTube Trending -> scoring boost.

Trends are fetched on an hourly cron (web/scheduler.py) and cached as JSON
under data/cache/trends/<region>.json. The RSS pipeline reads the cache; on
stale/missing cache it triggers an inline refresh (best-effort).

Match logic (see matcher.py):
- Whole-word substring match -> base boost
- rapidfuzz partial_ratio >= threshold -> softer boost
- Top-3 rank bonus
- Per-channel max_boost cap

Shared types live here so submodules don't have to import each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

TrendSource = Literal["google_daily", "youtube"]


@dataclass(frozen=True)
class TrendItem:
    term: str           # search term (google) or video title (youtube)
    source: TrendSource
    region: str         # ISO region code: TR, US, DE, ES, FR
    rank: int           # 1-based rank within source
    score: float        # rank-normalized weight 0..1 (higher = more trending)
    fetched_at: datetime


@dataclass(frozen=True)
class TrendCache:
    region: str
    fetched_at: datetime
    items: list[TrendItem]
    sources: list[str] = field(default_factory=list)

    def age_minutes(self) -> float:
        ft = (self.fetched_at if self.fetched_at.tzinfo
              else self.fetched_at.replace(tzinfo=timezone.utc))
        return (datetime.now(timezone.utc) - ft).total_seconds() / 60.0

    def is_fresh(self, max_age_minutes: float = 90.0) -> bool:
        return self.age_minutes() < max_age_minutes


__all__ = ["TrendItem", "TrendCache", "TrendSource"]
