"""Trend kanalında senaryo promptu: Google Trends bağlamı + 'neden gündemde' kuralı."""
from __future__ import annotations

from short_bot.models import NewsItem


def _channel(content_source="trends"):
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="gundem", name="Gündem", keywords=[], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 */2 * * *", duration_s=6, min_score=6.0, max_candidates_per_run=25,
        template="flas", colors={"primary": "#d0021b", "accent": "#ffe600",
                                 "bg_gradient": ["#3a3a3a", "#141414"]},
        handle="@gundem", output_dir="out", enabled=True, language="tr",
        content_source=content_source,
    )


def _item(desc, volume):
    return NewsItem(guid="https://x/1", title="Marmara 8 saatte 36 kez sallandı", link="https://x/1",
                    source="Milliyet", pub_date=None, thumb_url=None, description=desc,
                    trend_volume=volume)


def test_trend_channel_prompt_carries_search_context_and_rules():
    from short_bot.script_writer import build_script_prompt_for_channel
    item = _item("Google Trends · 100.000 arama · +%1.000 · istanbul deprem, adalar fayı · Son dakika: Marmara sallandı", 100000)
    p = build_script_prompt_for_channel(item, "gövde metni " * 20, _channel())
    assert "WHAT PEOPLE ARE SEARCHING FOR" in p
    assert "adalar fayı" in p                      # hangi soruların cevaplanacağını söyler
    assert "context sentence" in p.lower()
    # Arama sayısı EKRANA YAZILMAZ (kullanıcı bildirimi 2026-08-20)
    assert "NEVER write that the topic is trending" in p
    assert "why it is trending" not in p.lower()


def test_non_trend_channel_prompt_unchanged():
    from short_bot.script_writer import build_script_prompt_for_channel
    item = _item("Google Trends · 100.000 arama", 100000)
    p = build_script_prompt_for_channel(item, "gövde metni " * 20, _channel(content_source="rss"))
    assert "WHAT PEOPLE ARE SEARCHING FOR" not in p


def test_trend_channel_without_volume_data_has_no_block():
    from short_bot.script_writer import build_script_prompt_for_channel
    item = _item(None, 0)
    p = build_script_prompt_for_channel(item, "gövde metni " * 20, _channel())
    assert "WHAT PEOPLE ARE SEARCHING FOR" not in p
