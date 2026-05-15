"""Tests for short_bot.learning.injection.format_scorer_hint."""
from __future__ import annotations

import pytest

from short_bot.learning.injection import format_scorer_hint


def _insights(sample_size=10, top_cats=None, top_moods=None, leaders=None):
    return {
        "sample_size": sample_size,
        "top_categories": top_cats or [],
        "top_moods": top_moods or [],
        "watch_pct_leaders": leaders or [],
    }


def test_none_returns_empty():
    assert format_scorer_hint(None) == ""


def test_empty_dict_returns_empty():
    assert format_scorer_hint({}) == ""


def test_below_min_samples_returns_empty():
    """sample_size < 5 → no hint (data too sparse to trust)."""
    out = format_scorer_hint(_insights(sample_size=3, top_cats=[
        {"category": "Dünya", "n": 2, "avg_views": 1000, "avg_watch_pct": 50},
    ]))
    assert out == ""


def test_includes_category_block_when_enough_samples():
    out = format_scorer_hint(_insights(
        sample_size=10,
        top_cats=[
            {"category": "Dünya", "n": 4, "avg_views": 1625, "avg_watch_pct": 0},
            {"category": "Gündem", "n": 2, "avg_views": 1382, "avg_watch_pct": 91.7},
        ],
    ))
    assert "Dünya" in out
    assert "Gündem" in out
    assert "1625" in out


def test_excludes_categories_with_only_one_sample():
    """n=1 categories should not appear in the hint."""
    out = format_scorer_hint(_insights(
        sample_size=10,
        top_cats=[
            {"category": "Dünya", "n": 3, "avg_views": 1000, "avg_watch_pct": 0},
            {"category": "Sağlık", "n": 1, "avg_views": 5000, "avg_watch_pct": 0},
        ],
    ))
    assert "Dünya" in out
    assert "Sağlık" not in out


def test_mood_hint_only_when_enough_mood_samples():
    out = format_scorer_hint(_insights(
        sample_size=10,
        top_moods=[
            {"mood": "breaking", "n": 5, "avg_views": 1500, "avg_watch_pct": 50},
            {"mood": "neutral", "n": 1, "avg_views": 100, "avg_watch_pct": 10},
        ],
    ))
    # breaking n=5 → mentioned; neutral n=1 → NOT mentioned (below MIN_MOOD_SAMPLES=3)
    assert "breaking" in out
    assert "neutral" not in out


def test_mentions_kacin_for_low_mood_when_gap_is_large():
    out = format_scorer_hint(_insights(
        sample_size=10,
        top_moods=[
            {"mood": "breaking", "n": 8, "avg_views": 2000, "avg_watch_pct": 50},
            {"mood": "neutral", "n": 3, "avg_views": 50, "avg_watch_pct": 10},
        ],
    ))
    assert "breaking" in out
    # neutral 50 << breaking 2000/2=1000 → "kaçın"
    assert "kaçın" in out
    assert "neutral" in out


def test_watch_leaders_listed_as_concrete_examples():
    out = format_scorer_hint(_insights(
        sample_size=10,
        leaders=[
            {"title": "12. YARGI PAKETI MECLISTEN GECTI MI?",
             "views": 2764, "watch_pct": 183.3},
            {"title": "YASA DISI BAHIS OPERASYONU",
             "views": 1711, "watch_pct": 133.3},
        ],
    ))
    assert "YARGI PAKETI" in out
    assert "BAHIS" in out
    # Watch% rounded shown
    assert "183%" in out or "183 " in out


def test_caveat_line_present_when_hint_emitted():
    out = format_scorer_hint(_insights(
        sample_size=10,
        top_cats=[{"category": "X", "n": 3, "avg_views": 100, "avg_watch_pct": 0}],
    ))
    # Caveat: don't blindly inflate scores just because pattern matches
    assert "alakasız" in out.lower() or "alakasiz" in out.lower()
