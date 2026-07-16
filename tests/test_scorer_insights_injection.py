"""Scorer prompt integration with performance_insights param."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from short_bot.config import ChannelConfig
from short_bot.models import NewsItem
from short_bot.scorer import build_scoring_prompt, score_items


def _item(guid, title):
    return NewsItem(guid=guid, title=title, link="http://x", source="S",
                    pub_date=datetime(2026, 5, 16), thumb_url=None, description=None)


def _channel():
    return ChannelConfig(
        slug="test", name="Test", keywords=["x"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@t", output_dir="out",
        enabled=True, language="tr",
    )


def _strong_insights():
    return {
        "sample_size": 12,
        "top_categories": [
            {"category": "Dünya", "n": 4, "avg_views": 1625, "avg_watch_pct": 0},
            {"category": "Gündem", "n": 2, "avg_views": 1382, "avg_watch_pct": 91.7},
        ],
        "top_moods": [
            {"mood": "breaking", "n": 8, "avg_views": 1700, "avg_watch_pct": 25},
            {"mood": "neutral", "n": 3, "avg_views": 50, "avg_watch_pct": 5},
        ],
        "watch_pct_leaders": [
            {"title": "12. YARGI PAKETI", "views": 2764, "watch_pct": 183},
        ],
    }


# --- Default behavior (no insights) -----------------------------------------

def test_prompt_unchanged_when_insights_none():
    items = [_item("g1", "Some news headline")]
    base = build_scoring_prompt(items, channel=_channel())
    with_none = build_scoring_prompt(items, channel=_channel(),
                                       performance_insights=None)
    assert base == with_none


def test_prompt_unchanged_when_insights_too_sparse():
    items = [_item("g1", "Some news headline")]
    base = build_scoring_prompt(items, channel=_channel())
    sparse = {
        "sample_size": 2,
        "top_categories": [],
        "top_moods": [],
        "watch_pct_leaders": [],
    }
    out = build_scoring_prompt(items, channel=_channel(),
                                performance_insights=sparse)
    assert out == base


# --- With usable insights ---------------------------------------------------

def test_prompt_appends_hint_when_insights_strong():
    items = [_item("g1", "X")]
    base = build_scoring_prompt(items, channel=_channel())
    out = build_scoring_prompt(items, channel=_channel(),
                                performance_insights=_strong_insights())
    assert len(out) > len(base)
    assert "PERFORMANS" in out  # hint header
    assert "Dünya" in out
    assert "Gündem" in out
    assert "breaking" in out
    assert "YARGI PAKETI" in out


def test_score_items_passes_insights_to_prompt():
    """score_items forwards performance_insights through to build_scoring_prompt."""
    items = [_item("g1", "Test")]
    captured = {}

    def fake_run_json(prompt, schema, **kw):
        captured["prompt"] = prompt
        from short_bot.scorer import _ScoreResponse
        return _ScoreResponse.model_validate({"scores": [
            {"guid": "g1", "score": 7.0, "reasoning": "x"}
        ]})

    with patch("short_bot.scorer.run_json", side_effect=fake_run_json):
        score_items(items, claude_path="claude", channel=_channel(),
                    performance_insights=_strong_insights())

    assert "PERFORMANS" in captured["prompt"]
    assert "YARGI PAKETI" in captured["prompt"]


def test_score_items_no_insights_passes_clean_prompt():
    items = [_item("g1", "Test")]
    captured = {}

    def fake_run_json(prompt, schema, **kw):
        captured["prompt"] = prompt
        from short_bot.scorer import _ScoreResponse
        return _ScoreResponse.model_validate({"scores": [
            {"guid": "g1", "score": 7.0, "reasoning": "x"}
        ]})

    with patch("short_bot.scorer.run_json", side_effect=fake_run_json):
        score_items(items, claude_path="claude", channel=_channel())

    assert "PERFORMANS" not in captured["prompt"]
