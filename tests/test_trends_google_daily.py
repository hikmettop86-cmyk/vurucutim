"""Tests for short_bot.trends.google_daily."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from short_bot.trends.google_daily import fetch_google_daily_trends


def _mock_rss(titles: list[str], status: int = 200):
    """Build a minimal Google Trends RSS payload with given trending titles."""
    items = "".join(f"<item><title>{t}</title></item>" for t in titles)
    body = (
        f"<?xml version='1.0' encoding='UTF-8'?><rss><channel>{items}"
        f"</channel></rss>"
    )
    r = MagicMock()
    r.status_code = status
    r.content = body.encode("utf-8")
    r.text = body
    return r


def test_returns_trend_items_in_rank_order():
    r = _mock_rss(["Galatasaray", "Icardi", "Şampiyonlar Ligi"])
    with patch("short_bot.trends.google_daily.requests.get", return_value=r):
        items = fetch_google_daily_trends("TR")
    assert len(items) == 3
    assert items[0].term == "Galatasaray"
    assert items[0].rank == 1
    assert items[1].rank == 2
    assert items[0].score > items[2].score   # rank 1 score > rank 3 score
    assert all(i.source == "google_daily" for i in items)
    assert all(i.region == "TR" for i in items)


def test_returns_empty_on_http_error():
    r = _mock_rss([], status=429)
    with patch("short_bot.trends.google_daily.requests.get", return_value=r):
        items = fetch_google_daily_trends("TR")
    assert items == []


def test_returns_empty_on_request_exception():
    import requests
    with patch("short_bot.trends.google_daily.requests.get",
               side_effect=requests.RequestException("boom")):
        items = fetch_google_daily_trends("TR")
    assert items == []


def test_returns_empty_on_empty_feed():
    r = _mock_rss([])
    with patch("short_bot.trends.google_daily.requests.get", return_value=r):
        items = fetch_google_daily_trends("US")
    assert items == []


def test_respects_max_results_cap():
    r = _mock_rss([f"trend_{i}" for i in range(30)])
    with patch("short_bot.trends.google_daily.requests.get", return_value=r):
        items = fetch_google_daily_trends("DE", max_results=5)
    assert len(items) == 5


def test_region_uppercased_in_output():
    r = _mock_rss(["x"])
    with patch("short_bot.trends.google_daily.requests.get", return_value=r):
        items = fetch_google_daily_trends("tr")
    assert items[0].region == "TR"


def test_skips_empty_title_entries():
    r = _mock_rss(["Real Trend", "", "Another"])
    with patch("short_bot.trends.google_daily.requests.get", return_value=r):
        items = fetch_google_daily_trends("TR")
    # Empty title dropped, 2 real items kept
    assert [i.term for i in items] == ["Real Trend", "Another"]


def test_query_url_includes_geo_param():
    captured = {}
    def fake_get(url, timeout=None, headers=None):
        captured["url"] = url
        r = MagicMock()
        r.status_code = 200
        r.content = b"<rss><channel></channel></rss>"
        return r
    with patch("short_bot.trends.google_daily.requests.get", side_effect=fake_get):
        fetch_google_daily_trends("DE")
    assert "geo=DE" in captured["url"]
