"""Canlı Gündem masası: tablo, bölge, üretildi rozeti, tek tıkla üretim."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from short_bot.models import NewsItem
from short_bot.web import create_app

_SETTINGS = ("ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
             "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
             "claude_models: {dna: opus, default: haiku}\n")


def _ch(slug, voice=False):
    v = ("voice:\n  enabled: true\n  provider: cartesia\n  voice_id: v\n  speed: 1.05\n" if voice else "")
    return f"""\
slug: {slug}
name: {slug.title()}
keywords: []
language: tr
content_source: trends
trends_region: TR
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 25
template: flas
colors:
  primary: '#d0021b'
  accent: '#ffe600'
  bg_gradient: ['#3a3a3a', '#141414']
handle: '@{slug}'
output_dir: output/{slug}
enabled: true
{v}"""


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    (cfg_dir / "channels" / "gundem.yaml").write_text(_ch("gundem"), encoding="utf-8")
    (cfg_dir / "channels" / "gundem-yorum.yaml").write_text(_ch("gundem-yorum", voice=True), encoding="utf-8")
    (tmp_path / "data").mkdir()
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml", scheduler=False)


ITEMS = [
    NewsItem(guid="https://a/1", title="Marmara 8 saatte 36 kez sallandı", link="https://a/1", source="Milliyet",
             pub_date=datetime.now(timezone.utc), thumb_url="https://img/1.jpg",
             description="Google Trends · 100.000 arama · +%1.000 · istanbul deprem, adalar fayı · Başka başlık",
             trend_volume=100000, extra_links=("https://b/2",)),
    NewsItem(guid="https://c/3", title="Asgari ücrete ara zam", link="https://c/3", source="Dünya",
             pub_date=None, thumb_url=None, description="Google Trends · 10.000 arama · asgari ücret",
             trend_volume=10000),
]


@pytest.fixture
def fake_trends(monkeypatch):
    seen = {}

    def _fetch(region, **kw):
        seen["region"] = region; seen["kw"] = kw
        return ITEMS
    monkeypatch.setattr("short_bot.web.routes.gundem.fetch_trending_items", _fetch)
    return seen


def test_desk_renders_rows_and_channel_buttons(app, fake_trends):
    body = app.test_client().get("/gundem?region=TR").data.decode("utf-8")
    assert "Marmara 8 saatte 36 kez sallandı" in body and "100B+" in body and "%1.000" in body
    assert "adalar fayı" in body and "+1 kaynak daha" in body
    assert 'name="channel_slug" value="gundem"' in body and 'name="channel_slug" value="gundem-yorum"' in body
    assert "🎙️ Gündem Yorum" in body and "▶ Kart" in body
    assert 'hx-trigger="every 300s"' in body
    assert fake_trends["region"] == "TR" and fake_trends["kw"]["max_age_minutes"] == 30


def test_table_force_refresh_bypasses_cache(app, fake_trends):
    r = app.test_client().get("/gundem/table?region=TR&force=1")
    assert r.status_code == 200 and fake_trends["kw"]["max_age_minutes"] == 0


def test_desk_marks_produced(app, fake_trends, tmp_path):
    from short_bot.db import init_db, mark_processed
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, guid="https://a/1", channel="gundem", title="t")
    body = app.test_client().get("/gundem").data.decode("utf-8")
    assert "✓ Kart" in body
    assert body.count('name="channel_slug" value="gundem"') == 1   # yalnız ikinci satır için düğme


def test_produce_launches_pipeline_with_cached_item(app, fake_trends, monkeypatch):
    seen = {}

    def _launch(**kw):
        seen.update(kw)
    monkeypatch.setattr("short_bot.web.routes.gundem.launch_pipeline", _launch)
    r = app.test_client().post("/gundem/produce", data={"region": "TR", "channel_slug": "gundem-yorum",
                                                        "guid": "https://a/1"})
    assert r.status_code == 302
    assert seen["channel"].slug == "gundem-yorum" and seen["trigger"] == "manual_gundem"
    item = seen["preselected_item"]
    assert item.guid == "https://a/1" and item.trend_volume == 100000 and item.extra_links == ("https://b/2",)


def test_produce_unknown_guid_flashes(app, fake_trends, monkeypatch):
    monkeypatch.setattr("short_bot.web.routes.gundem.launch_pipeline",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("çağrılmamalı")))
    r = app.test_client().post("/gundem/produce", data={"channel_slug": "gundem", "guid": "https://yok"},
                               follow_redirects=True)
    assert r.status_code == 200 and "artık listede değil" in r.data.decode("utf-8")


def test_nav_has_gundem_link(app, fake_trends):
    body = app.test_client().get("/gundem").data.decode("utf-8")
    assert 'href="/gundem"' in body
