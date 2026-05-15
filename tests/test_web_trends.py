"""/trends view page + POST /trends/refresh tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.trends import TrendCache, TrendItem
from short_bot.trends.aggregator import _serialize
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n"
        "trends:\n  enabled: true\n  refresh_minutes: 60\n"
        "  default_sources: [google_daily]\n"
        "  cache_max_age_minutes: 90\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "tr-chan.yaml").write_text("""\
slug: tr-chan
name: TR Channel
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@trchan'
output_dir: output/tr-chan
enabled: true
cta:
  enabled: false
  text: ''
  icons: []
  duration_s: 0
  show_handle: false
trend_boost:
  enabled: true
  max_boost: 2.0
  min_term_length: 4
  fuzzy_threshold: 85
""", encoding="utf-8")
    (cfg_dir / "channels" / "off-chan.yaml").write_text("""\
slug: off-chan
name: Off Channel
keywords: [x]
language: en
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@off'
output_dir: output/off
enabled: true
cta:
  enabled: false
  text: ''
  icons: []
  duration_s: 0
  show_handle: false
""", encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)


def _write_cache(cache_dir: Path, region: str, terms: list[tuple[str, int]]):
    cache_dir.mkdir(parents=True, exist_ok=True)
    items = [
        TrendItem(term=t, source="google_daily", region=region, rank=r,
                  score=1.0 - (r - 1) / 20.0,
                  fetched_at=datetime.now(timezone.utc))
        for t, r in terms
    ]
    cache = TrendCache(
        region=region, fetched_at=datetime.now(timezone.utc),
        items=items, sources=["google_daily"],
    )
    (cache_dir / f"{region.lower()}.json").write_text(
        json.dumps(_serialize(cache), ensure_ascii=False),
        encoding="utf-8",
    )


# --- GET /trends ------------------------------------------------------------

def test_trends_page_renders_with_active_region(app, tmp_path):
    # Write a cache file the page should read + display
    cache_dir = tmp_path / "cache" / "trends"
    _write_cache(cache_dir, "TR", [("toki", 1), ("japonya", 2), ("liverpool", 3)])
    app.config["SHORTBOT_CACHE_DIR"] = tmp_path / "cache"

    body = app.test_client().get("/trends").data.decode("utf-8")
    assert "Trendler" in body
    assert "AKTIF" in body or "aktif" in body.lower()
    # Region heading + terms shown
    assert "TR" in body
    assert "toki" in body
    assert "japonya" in body
    assert "liverpool" in body


def test_trends_page_shows_channel_coverage_table(app, tmp_path):
    body = app.test_client().get("/trends").data.decode("utf-8")
    # Channel coverage table: tr-chan should be marked active, off-chan inactive
    assert "TR Channel" in body
    assert "Off Channel" in body
    assert "tr-chan" in body


def test_trends_page_no_active_channels_shows_hint(app, tmp_path):
    # Disable trend_boost on the active channel
    p = tmp_path / "config" / "channels" / "tr-chan.yaml"
    txt = p.read_text(encoding="utf-8").replace("enabled: true\n  max_boost",
                                                  "enabled: false\n  max_boost")
    p.write_text(txt, encoding="utf-8")

    body = app.test_client().get("/trends").data.decode("utf-8")
    assert "trend_boost.enabled=true" in body or "Bir kanal sec" in body


def test_trends_page_when_settings_disabled_shows_kapali(app, tmp_path):
    s_path = tmp_path / "config" / "settings.yaml"
    txt = s_path.read_text(encoding="utf-8").replace(
        "enabled: true", "enabled: false", 1)
    s_path.write_text(txt, encoding="utf-8")
    # Rebuild app to re-read settings
    from short_bot.web import create_app
    app2 = create_app(config_dir=tmp_path / "config",
                      db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)
    body = app2.test_client().get("/trends").data.decode("utf-8")
    assert "KAPALI" in body or "kapali" in body.lower()


# --- POST /trends/refresh ---------------------------------------------------

def test_refresh_button_triggers_aggregator(app, tmp_path):
    cache_dir = tmp_path / "cache" / "trends"
    app.config["SHORTBOT_CACHE_DIR"] = tmp_path / "cache"

    calls = []
    def fake_refresh(region, *, sources, youtube_api_key, cache_dir):
        calls.append((region, sources))
        return TrendCache(
            region=region, fetched_at=datetime.now(timezone.utc),
            items=[TrendItem(term="fresh", source="google_daily", region=region,
                             rank=1, score=1.0,
                             fetched_at=datetime.now(timezone.utc))],
            sources=sources,
        )
    with patch("short_bot.web.routes.trends.refresh_trends",
               side_effect=fake_refresh):
        resp = app.test_client().post("/trends/refresh", follow_redirects=False)
    # Redirect to /trends
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/trends")
    # tr-chan region=TR was refreshed
    assert any(c[0] == "TR" for c in calls)


def test_refresh_when_no_active_channels_flashes_error(app, tmp_path):
    # Disable trend_boost
    p = tmp_path / "config" / "channels" / "tr-chan.yaml"
    txt = p.read_text(encoding="utf-8").replace("enabled: true\n  max_boost",
                                                  "enabled: false\n  max_boost")
    p.write_text(txt, encoding="utf-8")

    with patch("short_bot.web.routes.trends.refresh_trends") as rm:
        resp = app.test_client().post("/trends/refresh", follow_redirects=True)
        rm.assert_not_called()
    body = resp.data.decode("utf-8")
    assert "Hicbir kanalda" in body or "trend_boost.enabled" in body


def test_refresh_when_settings_disabled_flashes_error(app, tmp_path):
    # Toggle settings.trends.enabled off in-memory
    s = app.config["SHORTBOT_SETTINGS"]
    from dataclasses import replace
    from short_bot.config import TrendsSettings
    new_trends = TrendsSettings(
        enabled=False, refresh_minutes=s.trends.refresh_minutes,
        default_sources=s.trends.default_sources,
        cache_max_age_minutes=s.trends.cache_max_age_minutes,
    )
    app.config["SHORTBOT_SETTINGS"] = replace(s, trends=new_trends)

    with patch("short_bot.web.routes.trends.refresh_trends") as rm:
        resp = app.test_client().post("/trends/refresh", follow_redirects=True)
        rm.assert_not_called()
    body = resp.data.decode("utf-8")
    assert "kapali" in body.lower() or "kapalı" in body.lower()


# --- nav link ---------------------------------------------------------------

def test_nav_includes_trendler_link(app):
    body = app.test_client().get("/").data.decode("utf-8")
    assert "/trends" in body
    assert "Trendler" in body
