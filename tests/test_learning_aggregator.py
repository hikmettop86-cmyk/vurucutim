"""Tests for short_bot.learning.aggregator.compute_channel_insights."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from short_bot.db import (init_db, record_short, record_youtube_upload,
                          upsert_video_stats)
from short_bot.learning.aggregator import compute_channel_insights


def _add_short_with_stats(eng, *, short_id_expected: int, channel: str,
                          title: str, category: str, mood: str,
                          views: int, avg_view_duration_s: float,
                          duration_s: int = 6, has_stats: bool = True,
                          age_days: int = 5):
    """Helper: insert short + youtube_upload + (optional) stats snapshot."""
    script_json = json.dumps({
        "header_top": title.split()[0] if title else "T",
        "header_bottom": "X",
        "photo_overlay": "y",
        "body_paragraph": "body text for " + title,
        "highlights": [],
        "category": category,
        "mood": mood,
    })
    sid = record_short(
        eng, channel=channel, rss_item_guid=f"g-{title}-{short_id_expected}",
        title=title, file_path=f"out/{title}.mp4",
        duration_s=duration_s, script_json=script_json, render_ms=100,
    )
    vid = f"V-{sid}"
    record_youtube_upload(
        eng, short_id=sid, video_id=vid,
        status="success", error=None,
        video_url=f"https://youtu.be/{vid}",
    )
    # Adjust uploaded_at to simulate age
    if age_days != 0:
        from short_bot.db import youtube_uploads
        ts = datetime.now(timezone.utc) - timedelta(days=age_days)
        with eng.begin() as conn:
            conn.execute(
                youtube_uploads.update()
                .where(youtube_uploads.c.short_id == sid)
                .values(uploaded_at=ts)
            )
    if has_stats:
        upsert_video_stats(
            eng, video_id=vid,
            snapshot_date=date.today(),
            views=views, likes=int(views * 0.02), comments=int(views * 0.005),
            watch_time_min=(views * avg_view_duration_s) / 60.0,
            avg_view_duration_s=avg_view_duration_s,
        )
    return sid


# --- Empty / sparse states ---------------------------------------------------

def test_empty_db_returns_zero_sample_size(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    out = compute_channel_insights(eng, "no-such-channel")
    assert out["sample_size"] == 0
    assert out["upload_count"] == 0
    assert out["top_categories"] == []
    assert out["top_view_examples"] == []


def test_uploads_without_stats_set_age_warning(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _add_short_with_stats(
        eng, short_id_expected=1, channel="c",
        title="A", category="Dünya", mood="breaking",
        views=0, avg_view_duration_s=0, has_stats=False,
    )
    out = compute_channel_insights(eng, "c")
    assert out["upload_count"] == 1
    assert out["sample_size"] == 0
    assert out["stats_age_warning"] is True


# --- Basic aggregation -------------------------------------------------------

def test_groups_by_category_filters_n1(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _add_short_with_stats(eng, short_id_expected=1, channel="c",
                          title="A1", category="Dünya", mood="breaking",
                          views=1000, avg_view_duration_s=3.0)
    _add_short_with_stats(eng, short_id_expected=2, channel="c",
                          title="A2", category="Dünya", mood="breaking",
                          views=2000, avg_view_duration_s=4.0)
    _add_short_with_stats(eng, short_id_expected=3, channel="c",
                          title="B1", category="Spor", mood="breaking",
                          views=500, avg_view_duration_s=2.0)  # n=1, filtered

    out = compute_channel_insights(eng, "c")
    cats = {c["category"]: c for c in out["top_categories"]}
    assert "Dünya" in cats
    assert cats["Dünya"]["n"] == 2
    assert cats["Dünya"]["total_views"] == 3000
    # Spor has n=1 → excluded
    assert "Spor" not in cats


def test_top_view_examples_sorted_desc(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _add_short_with_stats(eng, short_id_expected=1, channel="c",
                          title="Low", category="X", mood="breaking",
                          views=100, avg_view_duration_s=2.0)
    _add_short_with_stats(eng, short_id_expected=2, channel="c",
                          title="HIGH", category="X", mood="breaking",
                          views=5000, avg_view_duration_s=4.0)
    _add_short_with_stats(eng, short_id_expected=3, channel="c",
                          title="MID", category="X", mood="breaking",
                          views=1000, avg_view_duration_s=3.0)

    out = compute_channel_insights(eng, "c")
    titles = [s["title"] for s in out["top_view_examples"]]
    assert titles[0] == "HIGH"
    assert titles[1] == "MID"
    assert titles[2] == "Low"


def test_watch_pct_can_exceed_100_for_loop_engagement(tmp_path):
    """YouTube Shorts averageViewDuration counts loops, so >100% is valid."""
    eng = init_db(tmp_path / "x.sqlite")
    _add_short_with_stats(eng, short_id_expected=1, channel="c",
                          title="LoopWatch", category="X", mood="breaking",
                          views=100, avg_view_duration_s=12.0,  # 12s on a 6s short
                          duration_s=6)

    out = compute_channel_insights(eng, "c")
    leader = out["watch_pct_leaders"][0]
    assert leader["watch_pct"] == pytest.approx(200.0, abs=0.1)


def test_watch_pct_leaders_require_min_views(tmp_path):
    """Avoid noise from 1-view-1-loop outliers."""
    eng = init_db(tmp_path / "x.sqlite")
    # 3 views, watch% would be 100 — should be filtered out
    _add_short_with_stats(eng, short_id_expected=1, channel="c",
                          title="LowSample", category="X", mood="breaking",
                          views=3, avg_view_duration_s=6.0,
                          duration_s=6)
    out = compute_channel_insights(eng, "c")
    assert out["watch_pct_leaders"] == []


# --- Mood aggregation --------------------------------------------------------

def test_mood_aggregation(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    for i in range(3):
        _add_short_with_stats(eng, short_id_expected=i, channel="c",
                              title=f"B{i}", category="X", mood="breaking",
                              views=1000 + i*100, avg_view_duration_s=3.0)
    _add_short_with_stats(eng, short_id_expected=4, channel="c",
                          title="N1", category="X", mood="neutral",
                          views=50, avg_view_duration_s=1.0)

    out = compute_channel_insights(eng, "c")
    moods = {m["mood"]: m for m in out["top_moods"]}
    assert moods["breaking"]["n"] == 3
    assert moods["neutral"]["n"] == 1
    # Breaking should outrank neutral (higher avg_views, comes first)
    assert out["top_moods"][0]["mood"] == "breaking"


# --- Lookback filter ---------------------------------------------------------

def test_lookback_excludes_old_uploads(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _add_short_with_stats(eng, short_id_expected=1, channel="c",
                          title="Recent", category="X", mood="breaking",
                          views=100, avg_view_duration_s=3.0, age_days=5)
    _add_short_with_stats(eng, short_id_expected=2, channel="c",
                          title="Ancient", category="X", mood="breaking",
                          views=100, avg_view_duration_s=3.0, age_days=60)

    out = compute_channel_insights(eng, "c", lookback_days=30)
    titles = {s["title"] for s in out["top_view_examples"]}
    assert "Recent" in titles
    assert "Ancient" not in titles
    assert out["upload_count"] == 1


# --- Channel isolation -------------------------------------------------------

def test_channel_isolation(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _add_short_with_stats(eng, short_id_expected=1, channel="alpha",
                          title="A1", category="X", mood="breaking",
                          views=1000, avg_view_duration_s=3.0)
    _add_short_with_stats(eng, short_id_expected=2, channel="beta",
                          title="B1", category="X", mood="breaking",
                          views=500, avg_view_duration_s=3.0)

    out_alpha = compute_channel_insights(eng, "alpha")
    out_beta = compute_channel_insights(eng, "beta")
    assert out_alpha["sample_size"] == 1
    assert out_beta["sample_size"] == 1
    assert out_alpha["top_view_examples"][0]["title"] == "A1"
    assert out_beta["top_view_examples"][0]["title"] == "B1"
