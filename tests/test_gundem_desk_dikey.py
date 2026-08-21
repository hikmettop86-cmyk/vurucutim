"""Canlı Gündem masası dikeyi bilmeli + masa önbelleği boru hattını aç bırakmamalı."""
from __future__ import annotations

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
def genis_api(monkeypatch):
    """120 spor + 10 para trendi: masa 60'la kesse bile para havuzu korunmalı."""
    entries = ([_entry(f"mac-{i}", 100000 - i, (17,), i) for i in range(120)]
               + [_entry(f"zam-{i}", 3000 - i, (3,), 1000 + i) for i in range(10)])
    cagri = {"n": 0}

    def fake_now(region, *, language, hours=24, timeout_s=15):
        cagri["n"] += 1
        return entries

    def fake_arts(picked, *, language, region, timeout_s=15):
        return {i: [_article(f"H {e.term}", f"https://x.test/{e.term}")]
                for i, e in enumerate(picked)}

    monkeypatch.setattr("short_bot.trends.trending_now.fetch_trending_now", fake_now)
    monkeypatch.setattr("short_bot.trends.trending_now.fetch_trending_articles", fake_arts)
    return cagri


def test_limit_onbellegi_kucultmez(tmp_path, genis_api):
    """Masa `limit=60` ile çeker; boru hattı AYNI önbellekten para havuzunu
    eksiksiz görmeli. Eskiden masa max_entries=60 verip önbelleği 60 spora
    kilitliyordu ve para kanalı aç kalıyordu."""
    from short_bot.trends.trending_now import fetch_trending_items
    masa = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                min_volume=1000, limit=60)
    assert len(masa) == 60

    boru = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                min_volume=1000, vertical="para")
    assert len(boru) == 10, "masa önbelleği para havuzunu kesmiş"
    assert genis_api["n"] == 1, "ikinci çağrı önbellekten gelmeliydi"


def test_limit_suzgecten_SONRA_uygulanir(tmp_path, genis_api):
    """limit kesmesi dikey süzgecinden sonra olmalı; önce kesilirse dar dikey
    ilk N'de görünmez (havuzun %92'si spor)."""
    from short_bot.trends.trending_now import fetch_trending_items
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000, vertical="para", limit=5)
    assert len(items) == 5
    assert all(i.trend_categories == (3,) for i in items)


# --- masa süzgeci -------------------------------------------------------------

def _cfg(slug, dikey):
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug=slug, name=slug, keywords=[], language="tr", rss_locale="x",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, max_age_hours=24, template="flas",
        colors={"primary": "#f", "accent": "#0", "bg_gradient": ["#1", "#2"]},
        handle="@x", output_dir="o", enabled=False,
        content_source="trends", trends_region="TR", trends_vertical=dikey)


def _news(cats):
    from short_bot.models import NewsItem
    return NewsItem(guid=f"g{cats}", title="t", link="l", source=None, pub_date=None,
                    thumb_url=None, description=None, trend_volume=5000,
                    trend_categories=cats)


def test_kanal_dikeyleri_birlesimi():
    from short_bot.web.routes.gundem import _desk_verticals
    kanallar = [{"cfg": _cfg("a", "para")}, {"cfg": _cfg("b", "adalet")}]
    assert _desk_verticals(kanallar) == ["adalet", "para"]


def test_dikeysiz_kanal_birlesime_girmez():
    from short_bot.web.routes.gundem import _desk_verticals
    assert _desk_verticals([{"cfg": _cfg("a", None)}]) == []


def test_varsayilan_suzgec_kanal_dikeylerini_uygular():
    from short_bot.web.routes.gundem import _filter_by_dikey
    items = [_news((17,)), _news((3,)), _news((10,))]
    out = _filter_by_dikey(items, "", ["para"])
    assert [i.trend_categories for i in out] == [(3,)]


def test_tumu_secimi_hicbir_seyi_elemez():
    from short_bot.web.routes.gundem import _filter_by_dikey
    items = [_news((17,)), _news((3,))]
    assert len(_filter_by_dikey(items, "all", ["para"])) == 2


def test_acik_dikey_secimi_kanali_ezer():
    from short_bot.web.routes.gundem import _filter_by_dikey
    items = [_news((17,)), _news((3,))]
    out = _filter_by_dikey(items, "spor", ["para"])
    assert [i.trend_categories for i in out] == [(17,)]


def test_kanalin_dikeyi_yoksa_hepsi_gelir():
    """Dikeysiz kurulumda masa eski davranışını korur."""
    from short_bot.web.routes.gundem import _filter_by_dikey
    items = [_news((17,)), _news((3,))]
    assert len(_filter_by_dikey(items, "", [])) == 2
