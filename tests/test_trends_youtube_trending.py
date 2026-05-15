"""Tests for short_bot.trends.youtube_trending."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from short_bot.trends.youtube_trending import fetch_youtube_trending


def _mock_yt_response(titles: list[str]):
    """Build a fake youtubeAPI videos.list response."""
    return {
        "items": [
            {"snippet": {"title": t}} for t in titles
        ]
    }


def _patch_build(resp: dict):
    """Helper: patch googleapiclient.discovery.build so .videos().list().execute()
    returns resp."""
    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.return_value = resp
    return patch("short_bot.trends.youtube_trending.build", return_value=yt)


def test_returns_empty_when_api_key_missing():
    items = fetch_youtube_trending("", region="TR")
    assert items == []


def test_returns_titles_as_trend_items():
    resp = _mock_yt_response(["GS 3-0 FB ÖZET", "İcardi İlk Antrenmanı", "X"])
    with _patch_build(resp):
        items = fetch_youtube_trending("KEY", region="TR")
    assert len(items) == 3
    assert items[0].term == "GS 3-0 FB ÖZET"
    assert items[0].rank == 1
    assert items[0].source == "youtube"
    assert items[0].region == "TR"
    assert items[0].score > items[2].score


def test_returns_empty_on_httperror():
    from googleapiclient.errors import HttpError
    yt = MagicMock()
    yt.videos.return_value.list.return_value.execute.side_effect = HttpError(
        resp=MagicMock(status=403, reason="forbidden"),
        content=b"quota exceeded",
    )
    with patch("short_bot.trends.youtube_trending.build", return_value=yt):
        items = fetch_youtube_trending("KEY", region="TR")
    assert items == []


def test_returns_empty_on_unexpected_exception():
    with patch("short_bot.trends.youtube_trending.build",
               side_effect=RuntimeError("boom")):
        items = fetch_youtube_trending("KEY", region="TR")
    assert items == []


def test_region_uppercased_in_output_and_request():
    captured = {}
    yt = MagicMock()
    def fake_list(**kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.execute.return_value = {"items": [{"snippet": {"title": "x"}}]}
        return m
    yt.videos.return_value.list.side_effect = fake_list
    with patch("short_bot.trends.youtube_trending.build", return_value=yt):
        items = fetch_youtube_trending("KEY", region="tr")
    assert captured["regionCode"] == "TR"
    assert items[0].region == "TR"


def test_category_id_passed_through_when_provided():
    captured = {}
    yt = MagicMock()
    def fake_list(**kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.execute.return_value = {"items": []}
        return m
    yt.videos.return_value.list.side_effect = fake_list
    with patch("short_bot.trends.youtube_trending.build", return_value=yt):
        fetch_youtube_trending("KEY", region="TR", category_id="17")
    assert captured.get("videoCategoryId") == "17"


def test_category_id_omitted_when_none():
    captured = {}
    yt = MagicMock()
    def fake_list(**kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.execute.return_value = {"items": []}
        return m
    yt.videos.return_value.list.side_effect = fake_list
    with patch("short_bot.trends.youtube_trending.build", return_value=yt):
        fetch_youtube_trending("KEY", region="TR", category_id=None)
    assert "videoCategoryId" not in captured


def test_max_results_clamped_to_50():
    captured = {}
    yt = MagicMock()
    def fake_list(**kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.execute.return_value = {"items": []}
        return m
    yt.videos.return_value.list.side_effect = fake_list
    with patch("short_bot.trends.youtube_trending.build", return_value=yt):
        fetch_youtube_trending("KEY", region="TR", max_results=100)
    assert captured["maxResults"] == 50


def test_skips_items_with_missing_or_empty_title():
    resp = {"items": [
        {"snippet": {"title": "Good Title"}},
        {"snippet": {}},                     # no title
        {"snippet": {"title": ""}},          # empty
        {"snippet": {"title": "Another"}},
    ]}
    with _patch_build(resp):
        items = fetch_youtube_trending("KEY", region="TR")
    assert [i.term for i in items] == ["Good Title", "Another"]
