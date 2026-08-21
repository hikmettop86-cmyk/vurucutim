"""NewsItem.trend_categories — Google'ın kendi sınıflandırması üretimde ve
önbellekte hayatta kalmalı. Alan taşınmazsa dikey kapısı sessizce boş çalışır."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"


def _entry(**kw):
    from short_bot.trends.trending_now import TrendingEntry
    base = dict(term="altın", volume=100000, growth_pct=200,
                started_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
                category_ids=(3,), breakdown=("altın fiyatları",), news_ids=(1,))
    base.update(kw)
    return TrendingEntry(**base)


def _article(**kw):
    from short_bot.trends.trending_now import TrendingArticle
    base = dict(title="Altın rekor kırdı", url="https://x.test/1",
                source="Test", published_at=None, image_url=None)
    base.update(kw)
    return TrendingArticle(**base)


def test_kategori_news_iteme_tasinir():
    from short_bot.trends.trending_now import trending_as_news_items
    items = trending_as_news_items([_entry(category_ids=(3, 16))], {0: [_article()]})
    assert items[0].trend_categories == (3, 16)


def test_rss_kaynagi_bos_kategoriyle_gelir():
    from short_bot.models import NewsItem
    i = NewsItem(guid="g", title="t", link="l", source=None, pub_date=None,
                 thumb_url=None, description=None)
    assert i.trend_categories == ()


def test_onbellek_gidis_donusunde_korunur():
    from short_bot.trends.trending_now import (_item_from_dict, _item_to_dict,
                                               trending_as_news_items)
    items = trending_as_news_items([_entry(category_ids=(3, 16))], {0: [_article()]})
    geri = _item_from_dict(_item_to_dict(items[0]))
    assert geri.trend_categories == (3, 16)


def test_eski_onbellek_dosyasi_kirilmaz():
    # trend_categories alanı olmayan (bu değişiklikten önce yazılmış) kayıt.
    from short_bot.trends.trending_now import _item_from_dict
    geri = _item_from_dict({"guid": "g", "title": "t", "link": "l",
                            "trend_volume": 5000})
    assert geri.trend_categories == ()


def test_kategori_puanlama_zincirinde_dusmez():
    """ScoredItem'ı yeniden kuran her adım NewsItem'ı OLDUĞU GİBİ taşımalı."""
    from dataclasses import replace

    from short_bot.models import NewsItem, ScoredItem

    item = NewsItem(guid="g", title="t", link="l", source=None, pub_date=None,
                    thumb_url=None, description=None, trend_volume=5000,
                    trend_categories=(3, 16))
    s = ScoredItem(item=item, score=8.0, reasoning="", category="", subject="")
    # trend boost / kota / saga hepsi bu kalıbı kullanır
    boosted = replace(s, score=9.0)
    assert boosted.item.trend_categories == (3, 16)
