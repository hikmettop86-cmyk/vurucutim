"""Trend kanalı: puanlayıcı kapısı ve hacimli seçim."""
from __future__ import annotations

from short_bot.models import NewsItem, ScoredItem


def _channel(content_source="trends", language="tr", keywords=None):
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="gundem", name="Gündem", keywords=keywords or [],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 */2 * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=25,
        template="broadcast", colors={"primary": "#fff", "accent": "#000",
                                        "bg_gradient": ["#111", "#222"]},
        handle="@g", output_dir="out", enabled=True, language=language,
        content_source=content_source,
    )


def _item(guid, title, desc=None, volume=0):
    return NewsItem(guid=guid, title=title, link=guid, source=None, pub_date=None,
                    thumb_url=None, description=desc, trend_volume=volume)


# --- prompt -------------------------------------------------------------------

def test_trend_prompt_has_no_center_rule_and_lists_volume():
    from short_bot.scorer import build_scoring_prompt
    items = [_item("https://x/1", "Marmara 8 saatte 36 kez sallandı",
                   desc="Google Trends · 100.000 arama · +%1.000 · istanbul deprem",
                   volume=100000)]
    p = build_scoring_prompt(items, channel=_channel())
    assert "MERKEZ KURALI" not in p
    assert "KONU DIŞI" not in p
    assert "hava durumu" in p            # fayda-araması kapısı açıkça sayılıyor
    assert "100.000 arama" in p          # description satırda
    assert "guid=https://x/1" in p
    assert '"scores"' in p               # JSON sözleşmesi aynı


def test_trend_prompt_follows_channel_language():
    from short_bot.scorer import build_scoring_prompt
    items = [_item("g", "Tornado trifft Mannheim")]
    p_de = build_scoring_prompt(items, channel=_channel(language="de"))
    assert "Wetter" in p_de and "MERKEZ KURALI" not in p_de
    p_es = build_scoring_prompt(items, channel=_channel(language="es"))
    assert "weather" in p_es             # paket yoksa İngilizce


def test_rss_prompt_unchanged_for_non_trend_channels():
    from short_bot.scorer import build_scoring_prompt
    items = [_item("g", "Galatasaray kazandı")]
    p = build_scoring_prompt(items, channel=_channel(content_source="rss",
                                                      keywords=["galatasaray"]))
    assert "MERKEZ KURALI" in p


def test_trend_prompt_still_appends_category_and_saga_blocks():
    from dataclasses import replace
    from short_bot.scorer import build_scoring_prompt
    ch = replace(_channel(), categories=["spor", "ekonomi"], saga_penalty_per_repeat=1.0)
    p = build_scoring_prompt([_item("g", "x")], channel=ch)
    assert '"category"' in p and '"subject"' in p


# --- select_by_volume ---------------------------------------------------------

def _scored(guid, score, volume):
    return ScoredItem(item=_item(guid, guid, volume=volume), score=score, reasoning="")


def test_select_by_volume_prefers_volume_among_passing():
    from short_bot.scorer import select_by_volume
    scored = [_scored("dusuk_hacim_yuksek_puan", 9.5, 2000),
              _scored("yuksek_hacim", 7.0, 100000),
              _scored("elenen", 3.0, 500000)]
    out = select_by_volume(scored, min_score=6.0, n=3)
    assert [s.item.guid for s in out] == ["yuksek_hacim", "dusuk_hacim_yuksek_puan"]


def test_select_by_volume_ties_broken_by_score_and_respects_n():
    from short_bot.scorer import select_by_volume
    scored = [_scored("a", 6.5, 5000), _scored("b", 8.0, 5000), _scored("c", 7.0, 1000)]
    out = select_by_volume(scored, min_score=6.0, n=2)
    assert [s.item.guid for s in out] == ["b", "a"]


def test_select_by_volume_empty_when_none_pass():
    from short_bot.scorer import select_by_volume
    assert select_by_volume([_scored("a", 5.9, 99999)], min_score=6.0) == []
