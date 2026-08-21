"""Dikeyi olan kanalın havuzu aç kalırsa koşu boş biter — SESSİZCE genişlemez."""
from __future__ import annotations

import inspect

from short_bot.config import ChannelConfig


def _kanal(**kw):
    base = dict(
        slug="t", name="Test", keywords=[], language="tr",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, max_age_hours=24, template="flas",
        colors={"primary": "#fff", "accent": "#000", "bg_gradient": ["#1", "#2"]},
        handle="@t", output_dir="o", content_source="trends",
        rss_locale="hl=tr&gl=TR&ceid=TR:tr", enabled=False,
    )
    base.update(kw)
    return ChannelConfig(**base)


def test_dikeysiz_kanal_asla_ac_sayilmaz():
    """Dikey yoksa bu kapı hiç çalışmamalı: eski davranış bit bit aynı kalır."""
    from short_bot.pipeline import _vertical_starved
    assert _vertical_starved([], _kanal()) is False


def test_esigin_altinda_ac_sayilir():
    from short_bot.pipeline import _vertical_starved
    kanal = _kanal(trends_vertical="para", trends_min_candidates=4)
    assert _vertical_starved([1, 2, 3], kanal) is True


def test_esikte_ac_sayilmaz():
    from short_bot.pipeline import _vertical_starved
    kanal = _kanal(trends_vertical="para", trends_min_candidates=4)
    assert _vertical_starved([1, 2, 3, 4], kanal) is False


def test_pipeline_dikeyi_fetche_gecirir():
    """Dikey `fetch_trending_items`'a verilmezse süzgeç hiç çalışmaz ve
    kanal ayarı açık sanılıp kapalı çalışır."""
    from short_bot import pipeline
    src = inspect.getsource(pipeline._run_rss)
    assert "vertical=channel.trends_vertical" in src


def test_havuz_genisletme_kodu_yok():
    """Dikeyi düşürüp yeniden çekmek düzeltilen sorunu geri getirir."""
    from short_bot import pipeline
    src = inspect.getsource(pipeline._run_rss)
    assert "_vertical_starved" in src
    assert "vertical=None" not in src
