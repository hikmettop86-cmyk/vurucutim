"""Düzenleme POST'u FORMDA OLMAYAN alanı silmemeli.

channel_edit POST'u kanalı `ChannelConfig(...)` ile SIFIRDAN kuruyordu ve kodun
kendi yorumu bunu belgeliyordu: "burada sayılmayan her alan varsayılana düşer."
Sayılmayanlar: archived, saga_penalty_per_repeat, saga_window_days, categories,
category_quota_per_day, reference_channels.

Sonucu: kanalı panelden BİR KEZ kaydetmek saga sınırını kapatıyor ve pasife
alınmış kanalı geri aktif ediyordu — formda o alanlar hiç olmadığı hâlde.
Aynı aile: trends_min_volume'un 5000'den 1000'e sessizce inmesi (o zaten
tek tek eklenerek yamanmıştı).
"""
from __future__ import annotations

import pytest

from short_bot.config import load_channel
from short_bot.web import create_app

_SETTINGS = (
    "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
    "web: {host: 127.0.0.1, port: 5005}\n"
    "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
)

_YAML = (
    "slug: ch\nname: C\nkeywords: [a]\nlanguage: tr\n"
    "rss_locale: 'hl=tr&gl=TR&ceid=TR:tr'\n"
    "schedule_cron: '0 9 * * *'\nduration_s: 6\nmin_score: 6.0\n"
    "max_candidates_per_run: 10\ntemplate: newscast\n"
    "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
    "handle: '@ch'\noutput_dir: out\nenabled: true\n"
    "archived: true\n"
    "saga_penalty_per_repeat: 1.5\nsaga_window_days: 21\n"
    "categories: [transfer, yonetim]\n"
    "category_quota_per_day: {transfer: 2}\n"
    "reference_channels: ['@rakip']\n"
    "trends_min_volume: 5000\n"
)


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    (cfg_dir / "channels" / "ch.yaml").write_text(_YAML, encoding="utf-8")
    return create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates", music_root=tmp_path / "music",
        cache_dir=tmp_path / "cache", lock_dir=tmp_path / "locks",
        logs_dir=tmp_path / "logs", output_root=tmp_path / "out", scheduler=False)


def _kaydet(app, **ek):
    data = {"schedule_cron": "0 9 * * *", "duration_s": "6", "min_score": "6.0",
            "max_candidates_per_run": "10", "handle": "@ch", "name": "C"}
    data.update(ek)
    app.test_client().post("/channels/ch/edit", data=data, follow_redirects=True)
    return load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "ch.yaml")


@pytest.mark.parametrize("alan,beklenen", [
    ("saga_penalty_per_repeat", 1.5),
    ("saga_window_days", 21),
    ("categories", ["transfer", "yonetim"]),
    ("category_quota_per_day", {"transfer": 2}),
    ("reference_channels", ["@rakip"]),
    ("trends_min_volume", 5000),
])
def test_formda_olmayan_alan_kaydetmede_kaybolmaz(app, alan, beklenen):
    cfg = _kaydet(app)
    assert getattr(cfg, alan) == beklenen, f"{alan} kaydetmede sıfırlandı"


def test_pasiflik_kaydetmede_kaybolmaz(app):
    """`archived` formda yoksa korunmalı; varsa okunmalı."""
    assert _kaydet(app).archived is True          # formda yok → korunur
    assert _kaydet(app, archived_present="1").archived is False   # kutu işaretsiz
    # Not: ikinci kaydet archived'i False yaptı; üçüncüde geri açılabilmeli.
    assert _kaydet(app, archived_present="1", archived="1").archived is True


def test_ad_degistirilebilir(app):
    """Kanal ADI bu sayfada hiç yoktu — POST `name=cfg.name` yazıyordu."""
    assert _kaydet(app, name="Yeni Ad").name == "Yeni Ad"
