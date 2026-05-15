"""Tests for short_bot.trends.aggregator — refresh + cache I/O."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from short_bot.trends import TrendCache, TrendItem
from short_bot.trends.aggregator import (
    _deserialize, _serialize, get_or_refresh,
    load_trends_cache, refresh_trends,
)


def _trend(term: str, *, source="google_daily", rank=1, region="TR") -> TrendItem:
    return TrendItem(
        term=term, source=source, region=region, rank=rank,
        score=1.0 - (rank - 1) / 20.0,
        fetched_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )


def _mock_google(items):
    return patch("short_bot.trends.aggregator.fetch_google_daily_trends",
                  return_value=items)


def _mock_youtube(items):
    return patch("short_bot.trends.aggregator.fetch_youtube_trending",
                  return_value=items)


# --- refresh_trends ---------------------------------------------------------

def test_refresh_combines_both_sources(tmp_path):
    g = [_trend("Galatasaray", source="google_daily")]
    y = [_trend("İcardi Antrenmanı", source="youtube")]
    with _mock_google(g), _mock_youtube(y):
        cache = refresh_trends(
            "TR", sources=["google_daily", "youtube"],
            youtube_api_key="KEY", cache_dir=tmp_path,
        )
    terms = {i.term for i in cache.items}
    assert "Galatasaray" in terms
    assert "İcardi Antrenmanı" in terms


def test_refresh_skips_youtube_when_no_api_key(tmp_path):
    g = [_trend("X")]
    with _mock_google(g), _mock_youtube([_trend("Y", source="youtube")]) as ym:
        cache = refresh_trends(
            "TR", sources=["google_daily", "youtube"],
            youtube_api_key="", cache_dir=tmp_path,
        )
        # youtube fetcher must NOT have been called
        ym.assert_not_called()
    terms = {i.term for i in cache.items}
    assert terms == {"X"}


def test_refresh_dedups_same_term_across_sources(tmp_path):
    g = [_trend("Galatasaray", source="google_daily", rank=5)]      # score 0.8
    y = [_trend("Galatasaray", source="youtube", rank=1)]           # score 1.0
    with _mock_google(g), _mock_youtube(y):
        cache = refresh_trends(
            "TR", sources=["google_daily", "youtube"],
            youtube_api_key="KEY", cache_dir=tmp_path,
        )
    assert len(cache.items) == 1
    # higher-score copy kept (youtube here)
    assert cache.items[0].source == "youtube"


def test_refresh_writes_cache_file(tmp_path):
    g = [_trend("Galatasaray")]
    with _mock_google(g), _mock_youtube([]):
        refresh_trends("TR", sources=["google_daily"],
                       youtube_api_key="", cache_dir=tmp_path)
    f = tmp_path / "tr.json"
    assert f.exists()
    payload = json.loads(f.read_text(encoding="utf-8"))
    assert payload["region"] == "TR"
    assert len(payload["items"]) == 1


def test_refresh_returns_empty_cache_when_all_sources_fail(tmp_path):
    with _mock_google([]), _mock_youtube([]):
        cache = refresh_trends(
            "TR", sources=["google_daily", "youtube"],
            youtube_api_key="KEY", cache_dir=tmp_path,
        )
    assert cache.items == []
    assert cache.region == "TR"


def test_refresh_does_not_write_cache_when_cache_dir_none():
    g = [_trend("X")]
    with _mock_google(g), _mock_youtube([]):
        cache = refresh_trends("TR", sources=["google_daily"],
                                youtube_api_key="", cache_dir=None)
    assert len(cache.items) == 1


def test_refresh_skips_unrequested_source(tmp_path):
    g = [_trend("Should appear")]
    with _mock_google(g), _mock_youtube([]) as ym:
        refresh_trends("TR", sources=["google_daily"],
                       youtube_api_key="KEY", cache_dir=tmp_path)
        ym.assert_not_called()


# --- load_trends_cache ------------------------------------------------------

def test_load_returns_none_when_missing(tmp_path):
    assert load_trends_cache("TR", tmp_path) is None


def test_load_returns_none_on_invalid_json(tmp_path):
    (tmp_path / "tr.json").write_text("{not valid json", encoding="utf-8")
    assert load_trends_cache("TR", tmp_path) is None


def test_round_trip_serialize_deserialize():
    cache = TrendCache(
        region="TR",
        fetched_at=datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc),
        items=[_trend("X"), _trend("Y", rank=2)],
        sources=["google_daily"],
    )
    raw = _serialize(cache)
    rebuilt = _deserialize(raw)
    assert rebuilt.region == cache.region
    assert len(rebuilt.items) == 2
    assert rebuilt.items[0].term == "X"
    assert rebuilt.sources == ["google_daily"]


def test_load_returns_cache_after_refresh(tmp_path):
    g = [_trend("Galatasaray")]
    with _mock_google(g), _mock_youtube([]):
        refresh_trends("TR", sources=["google_daily"],
                       youtube_api_key="", cache_dir=tmp_path)
    cache = load_trends_cache("TR", tmp_path)
    assert cache is not None
    assert cache.items[0].term == "Galatasaray"


# --- get_or_refresh ---------------------------------------------------------

def test_get_or_refresh_uses_fresh_cache(tmp_path):
    """When cache is fresh, refresh_trends must not be called."""
    # Write a fresh cache file
    fresh = TrendCache(
        region="TR",
        fetched_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        items=[_trend("CachedTerm")],
        sources=["google_daily"],
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tr.json").write_text(
        json.dumps(_serialize(fresh), ensure_ascii=False),
        encoding="utf-8",
    )
    with patch("short_bot.trends.aggregator.refresh_trends") as rm:
        cache = get_or_refresh(
            "TR", sources=["google_daily"], youtube_api_key="",
            cache_dir=tmp_path, max_age_minutes=60,
        )
        rm.assert_not_called()
    assert cache.items[0].term == "CachedTerm"


def test_get_or_refresh_refreshes_when_stale(tmp_path):
    stale = TrendCache(
        region="TR",
        fetched_at=datetime.now(timezone.utc) - timedelta(hours=5),
        items=[_trend("OldTerm")],
        sources=["google_daily"],
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tr.json").write_text(
        json.dumps(_serialize(stale), ensure_ascii=False), encoding="utf-8",
    )
    with _mock_google([_trend("FreshTerm")]), _mock_youtube([]):
        cache = get_or_refresh(
            "TR", sources=["google_daily"], youtube_api_key="",
            cache_dir=tmp_path, max_age_minutes=60,
        )
    assert cache.items[0].term == "FreshTerm"


def test_get_or_refresh_falls_back_to_stale_when_refresh_empty(tmp_path):
    stale = TrendCache(
        region="TR",
        fetched_at=datetime.now(timezone.utc) - timedelta(hours=5),
        items=[_trend("OldButValid")],
        sources=["google_daily"],
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tr.json").write_text(
        json.dumps(_serialize(stale), ensure_ascii=False), encoding="utf-8",
    )
    # refresh returns empty (network down)
    with _mock_google([]), _mock_youtube([]):
        cache = get_or_refresh(
            "TR", sources=["google_daily"], youtube_api_key="",
            cache_dir=tmp_path, max_age_minutes=60,
        )
    # Falls back to stale
    assert cache is not None
    assert cache.items[0].term == "OldButValid"


def test_get_or_refresh_returns_none_when_no_cache_and_refresh_empty(tmp_path):
    with _mock_google([]), _mock_youtube([]):
        cache = get_or_refresh(
            "TR", sources=["google_daily"], youtube_api_key="",
            cache_dir=tmp_path,
        )
    assert cache is None
