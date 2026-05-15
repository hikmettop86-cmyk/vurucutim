"""Integration tests for trend boost wiring inside pipeline._apply_trend_boost."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.config import ChannelConfig, Settings, TrendBoostConfig, TrendsSettings
from short_bot.models import NewsItem, ScoredItem
from short_bot.pipeline import _apply_trend_boost
from short_bot.trends import TrendCache, TrendItem


def _settings(*, trends_enabled: bool = True) -> Settings:
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1", web_port=5005,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"default": "haiku"},
        trends=TrendsSettings(
            enabled=trends_enabled, refresh_minutes=60,
            default_sources=("google_daily",), cache_max_age_minutes=90.0,
        ),
    )


def _channel(*, trend_boost: TrendBoostConfig | None) -> ChannelConfig:
    return ChannelConfig(
        slug="test", name="Test", keywords=["x"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=10, template="newscast",
        colors={"primary": "#fff"}, handle="@t", output_dir="out",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False, language="tr",
        trend_boost=trend_boost,
    )


def _item(guid: str, title: str) -> NewsItem:
    return NewsItem(guid=guid, title=title, link="http://x", source="S",
                    pub_date=datetime(2026, 5, 15), thumb_url=None,
                    description=None)


def _scored(items_titles, scores) -> list[ScoredItem]:
    return [
        ScoredItem(item=_item(f"g{i}", t), score=s, reasoning="r")
        for i, (t, s) in enumerate(zip(items_titles, scores))
    ]


def _trend_cache(terms_with_rank: list[tuple[str, int]]) -> TrendCache:
    items = [
        TrendItem(term=t, source="google_daily", region="TR", rank=r,
                  score=1.0 - (r - 1) / 20.0,
                  fetched_at=datetime.now(timezone.utc))
        for t, r in terms_with_rank
    ]
    return TrendCache(region="TR", fetched_at=datetime.now(timezone.utc),
                      items=items, sources=["google_daily"])


def _log() -> logging.Logger:
    return logging.getLogger("test.trend_boost")


# --- gating: channel/setting toggles ----------------------------------------

def test_no_boost_when_channel_trend_boost_none(tmp_path):
    scored = _scored(["Galatasaray won"], [7.0])
    out = _apply_trend_boost(
        scored, channel=_channel(trend_boost=None), settings=_settings(),
        cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
    )
    assert out == scored


def test_no_boost_when_channel_disabled(tmp_path):
    tb = TrendBoostConfig(enabled=False)
    scored = _scored(["Galatasaray won"], [7.0])
    out = _apply_trend_boost(
        scored, channel=_channel(trend_boost=tb),
        settings=_settings(), cache_dir=tmp_path,
        secrets_path=tmp_path / "s.yaml", log=_log(),
    )
    assert out == scored


def test_no_boost_when_global_settings_disabled(tmp_path):
    tb = TrendBoostConfig(enabled=True)
    scored = _scored(["Galatasaray won"], [7.0])
    out = _apply_trend_boost(
        scored, channel=_channel(trend_boost=tb),
        settings=_settings(trends_enabled=False),
        cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
    )
    assert out == scored


def test_empty_scored_returns_empty(tmp_path):
    tb = TrendBoostConfig(enabled=True)
    out = _apply_trend_boost(
        [], channel=_channel(trend_boost=tb), settings=_settings(),
        cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
    )
    assert out == []


# --- happy path -------------------------------------------------------------

def test_boost_applied_when_headline_matches_trend(tmp_path):
    tb = TrendBoostConfig(enabled=True, max_boost=2.0)
    scored = _scored(
        ["Galatasaray Fenerbahce derbisi", "İlgisiz bir haber"],
        [6.5, 8.0],
    )
    cache = _trend_cache([("Galatasaray", 1)])
    with patch("short_bot.trends.aggregator.get_or_refresh", return_value=cache), \
         patch("short_bot.pipeline._load_secrets", return_value={}):
        out = _apply_trend_boost(
            scored, channel=_channel(trend_boost=tb), settings=_settings(),
            cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
        )
    # First item boosted (Galatasaray rank=1: 1.0+0.5 bonus = 1.5)
    assert out[0].score == 8.0  # 6.5 + 1.5
    # Second untouched
    assert out[1].score == 8.0
    assert "trend+" in out[0].reasoning


def test_boost_caps_score_at_10(tmp_path):
    tb = TrendBoostConfig(enabled=True, max_boost=3.0)
    scored = _scored(["Galatasaray Icardi transfer şoku"], [9.5])
    cache = _trend_cache([
        ("Galatasaray", 1),  # 1.5
        ("Icardi", 2),       # 1.5
    ])
    with patch("short_bot.trends.aggregator.get_or_refresh", return_value=cache), \
         patch("short_bot.pipeline._load_secrets", return_value={}):
        out = _apply_trend_boost(
            scored, channel=_channel(trend_boost=tb), settings=_settings(),
            cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
        )
    assert out[0].score == 10.0  # clamped from 9.5 + 3.0


def test_no_cache_returns_scored_unchanged(tmp_path):
    tb = TrendBoostConfig(enabled=True)
    scored = _scored(["Anything"], [7.0])
    with patch("short_bot.trends.aggregator.get_or_refresh", return_value=None), \
         patch("short_bot.pipeline._load_secrets", return_value={}):
        out = _apply_trend_boost(
            scored, channel=_channel(trend_boost=tb), settings=_settings(),
            cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
        )
    assert out == scored


def test_refresh_exception_does_not_break_pipeline(tmp_path):
    tb = TrendBoostConfig(enabled=True)
    scored = _scored(["Anything"], [7.0])
    with patch("short_bot.trends.aggregator.get_or_refresh",
               side_effect=RuntimeError("boom")), \
         patch("short_bot.pipeline._load_secrets", return_value={}):
        out = _apply_trend_boost(
            scored, channel=_channel(trend_boost=tb), settings=_settings(),
            cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
        )
    assert out == scored


def test_region_override_passed_through(tmp_path):
    tb = TrendBoostConfig(enabled=True, region_override="GB")
    scored = _scored(["x"], [7.0])
    captured = {}
    def fake_get(region, **kw):
        captured["region"] = region
        return None
    with patch("short_bot.trends.aggregator.get_or_refresh",
               side_effect=fake_get), \
         patch("short_bot.pipeline._load_secrets", return_value={}):
        _apply_trend_boost(
            scored, channel=_channel(trend_boost=tb), settings=_settings(),
            cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
        )
    assert captured["region"] == "GB"


def test_channel_sources_override_settings_default(tmp_path):
    tb = TrendBoostConfig(enabled=True, sources=["youtube"])
    scored = _scored(["x"], [7.0])
    captured = {}
    def fake_get(region, **kw):
        captured["sources"] = kw["sources"]
        return None
    with patch("short_bot.trends.aggregator.get_or_refresh",
               side_effect=fake_get), \
         patch("short_bot.pipeline._load_secrets", return_value={}):
        _apply_trend_boost(
            scored, channel=_channel(trend_boost=tb), settings=_settings(),
            cache_dir=tmp_path, secrets_path=tmp_path / "s.yaml", log=_log(),
        )
    assert captured["sources"] == ["youtube"]
