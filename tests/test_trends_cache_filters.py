"""Önbellek BÖLGE başınadır, kanal başına değil: hacim tabanı ve dikey kanal
ayarıdır ve önbelleğe SIZMAMALI."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest


def _entry(term, volume, cats, nid):
    from short_bot.trends.trending_now import TrendingEntry
    return TrendingEntry(term=term, volume=volume, growth_pct=0,
                         started_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
                         category_ids=cats, breakdown=(), news_ids=(nid,))


def _article(title, url):
    from short_bot.trends.trending_now import TrendingArticle
    return TrendingArticle(title=title, url=url, source="S",
                           published_at=None, image_url=None)


@pytest.fixture
def sahte_api(monkeypatch):
    """Üç trend: spor/yüksek, para/orta, para/düşük."""
    entries = [
        _entry("galatasaray", 100000, (17,), 1),
        _entry("altın", 5000, (3,), 2),
        _entry("mevduat faizi", 1500, (3,), 3),
    ]
    arts = {"galatasaray": [_article("GS kazandı", "https://x.test/1")],
            "altın": [_article("Altın rekor", "https://x.test/2")],
            "mevduat faizi": [_article("Faiz güncellendi", "https://x.test/3")]}
    cagri = {"n": 0}

    def fake_now(region, *, language, hours=24, timeout_s=15):
        cagri["n"] += 1
        return entries

    def fake_arts(picked, *, language, region, timeout_s=15):
        return {i: arts[e.term] for i, e in enumerate(picked)}

    monkeypatch.setattr("short_bot.trends.trending_now.fetch_trending_now", fake_now)
    monkeypatch.setattr("short_bot.trends.trending_now.fetch_trending_articles", fake_arts)
    return cagri


def test_dikey_havuzu_daraltir(tmp_path, sahte_api):
    from short_bot.trends.trending_now import fetch_trending_items
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000, vertical="para")
    assert [i.title for i in items] == ["Altın rekor", "Faiz güncellendi"]


def test_onbellek_dikeyden_etkilenmez(tmp_path, sahte_api):
    """Para kanalı önbelleği doldurur; spor kanalı AYNI önbellekten kendi
    adaylarını görmeli — filtre önbelleğe yazılsaydı boş dönerdi."""
    from short_bot.trends.trending_now import fetch_trending_items
    fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                         min_volume=1000, vertical="para")
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000, vertical="spor")
    assert [i.title for i in items] == ["GS kazandı"]
    assert sahte_api["n"] == 1          # ikinci çağrı önbellekten geldi


def test_onbellek_hacim_tabanindan_etkilenmez(tmp_path, sahte_api):
    """Tabanı 5000 olan kanal önbelleği doldurur; tabanı 1000 olan kanal
    yine de düşük hacimli adayını görmeli."""
    from short_bot.trends.trending_now import fetch_trending_items
    fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                         min_volume=5000, vertical="para")
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000, vertical="para")
    assert len(items) == 2
    assert sahte_api["n"] == 1


def test_dikeysiz_kanal_hepsini_alir(tmp_path, sahte_api):
    from short_bot.trends.trending_now import fetch_trending_items
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000)
    assert len(items) == 3


def test_dikeyli_kanalda_rss_yedegi_kullanilmaz(tmp_path, monkeypatch, caplog):
    """RSS yedeğinde kategori YOK. Dikeyli kanala vermek 'her şey'e dönmektir."""

    def patla(region, *, language, hours=24, timeout_s=15):
        raise RuntimeError("API down")

    rss_cagrildi = {"n": 0}

    def fake_rss(region, *, timeout_s=10):
        rss_cagrildi["n"] += 1
        return []

    monkeypatch.setattr("short_bot.trends.trending_now.fetch_trending_now", patla)
    monkeypatch.setattr("short_bot.trends.trending_now._rss_fallback", fake_rss)
    from short_bot.trends.trending_now import fetch_trending_items
    with caplog.at_level(logging.INFO):
        items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                     min_volume=1000, vertical="para")
    assert items == []
    assert rss_cagrildi["n"] == 0
    assert "RSS yedeği" in caplog.text
