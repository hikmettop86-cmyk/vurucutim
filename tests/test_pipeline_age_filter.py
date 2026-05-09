"""Tests for RSS item age filtering in pipeline._is_recent."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from short_bot.pipeline import _is_recent


def test_recent_item_kept():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    pub = datetime.now(timezone.utc) - timedelta(hours=2)
    assert _is_recent(pub, cutoff) is True


def test_old_item_dropped():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    pub = datetime.now(timezone.utc) - timedelta(hours=72)
    assert _is_recent(pub, cutoff) is False


def test_item_at_cutoff_kept():
    """Boundary: item exactly at cutoff is kept (>= comparison)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    assert _is_recent(cutoff, cutoff) is True


def test_naive_datetime_treated_as_utc():
    """feedparser dateparser sometimes returns naive datetimes — must not crash."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    naive_recent = datetime.utcnow() - timedelta(hours=2)
    assert _is_recent(naive_recent, cutoff) is True

    naive_old = datetime.utcnow() - timedelta(hours=72)
    assert _is_recent(naive_old, cutoff) is False


def test_none_pub_date_dropped():
    """Items without a published date are excluded — Google News normally provides one;
    missing date most often signals a re-syndicated aggregator entry."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    assert _is_recent(None, cutoff) is False


def test_pub_with_non_utc_tz_normalized():
    """Items with non-UTC tzinfo are normalized via astimezone semantics."""
    tz_plus3 = timezone(timedelta(hours=3))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    pub = datetime.now(tz_plus3) - timedelta(hours=2)
    assert _is_recent(pub, cutoff) is True


def test_negative_keywords_filter_drops_matches():
    """Items whose title contains any negative keyword are dropped (case-insensitive)."""
    from short_bot.pipeline import _filter_negative_keywords
    from short_bot.models import NewsItem
    items = [
        NewsItem(guid="1", title="WWE Backlash 2026 Results",
                 link="x", description="", source="x",
                 pub_date=None, thumb_url=None),
        NewsItem(guid="2", title="NFL Rookie Minicamps Update",
                 link="x", description="", source="x",
                 pub_date=None, thumb_url=None),
    ]
    out = _filter_negative_keywords(items, ["wwe", "wrestling"])
    assert len(out) == 1
    assert out[0].guid == "2"


def test_negative_keywords_empty_list_keeps_all():
    from short_bot.pipeline import _filter_negative_keywords
    from short_bot.models import NewsItem
    items = [NewsItem(guid="1", title="A", link="x", description="",
                       source="x", pub_date=None, thumb_url=None)]
    assert _filter_negative_keywords(items, []) == items


def test_negative_keywords_substring_match():
    """Substring match (case-insensitive). 'wrestler' should match 'wrestl'."""
    from short_bot.pipeline import _filter_negative_keywords
    from short_bot.models import NewsItem
    items = [NewsItem(guid="1", title="The wrestler returns", link="x",
                       description="", source="x", pub_date=None, thumb_url=None)]
    out = _filter_negative_keywords(items, ["wrestl"])
    assert out == []
