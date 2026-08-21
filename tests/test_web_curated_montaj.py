"""Reel formatı kalkıyor — montaj ayarları Kürate'nin kendi alanları oluyor.

Reel canlıda tek kanalı olmayan bir formattı ama `edit_reel.html.j2` (33 KB)
montaj ayarlarının TEK arayüzüydü. Kürate sayfası bunların bir kısmını zaten
devralmıştı (zoom, whoosh, flash, oklar, varyasyonlar, müzik havası); eksik
kalanlar burada test ediliyor.

Ölçüm: bu alanların hepsi 2–10 modülde okunuyor, hiçbiri ölü değil. Taşımamak
özellik kaybı olurdu.
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
    "slug: kur\nname: Kür\nhandle: '@kur'\nkeywords: [a]\nlanguage: tr\n"
    "schedule_cron: '0 10 * * *'\nduration_s: 6\nmin_score: 6.0\n"
    "max_candidates_per_run: 10\ntemplate: newscast\n"
    "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
    "output_dir: out\nenabled: true\ncontent_source: curated\n"
    "reel:\n  enabled: true\n  voice_id: v1\n  highlight_color: '#38bdf8'\n"
    "  target_duration_s: [45, 60]\n  cut_pacing: medium\n  music_volume: 0.12\n"
)

# Ana montaj alanları — kürate videosunun temposunu ve biçimini belirler.
ANA = ("target_min", "target_max", "cut_pacing", "layout", "font",
       "music_volume", "verify_footage", "series_enabled")

# İkincil montaj alanları — "Gelişmiş" bölümünde.
GELISMIS = ("arc_mode", "color_grade", "comment_question", "identity_lock",
            "interrupts", "subject_framing", "tempo_zones", "music_duck",
            "visual_loop", "sting_enabled", "number_pop", "speed")


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    (cfg_dir / "channels" / "kur.yaml").write_text(_YAML, encoding="utf-8")
    return create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates", music_root=tmp_path / "music",
        cache_dir=tmp_path / "cache", lock_dir=tmp_path / "locks",
        logs_dir=tmp_path / "logs", output_root=tmp_path / "out", scheduler=False)


@pytest.mark.parametrize("alan", ANA + GELISMIS)
def test_montaj_alani_cizilir(app, alan):
    html = app.test_client().get("/channels/kur/edit-curated").get_data(as_text=True)
    assert f'name="{alan}"' in html, f"kürate sayfasında {alan} yok"


def test_sure_araligi_kaydedilir(app):
    app.test_client().post("/channels/kur/edit-curated", data={
        "name": "Kür", "target_min": "30", "target_max": "40",
    }, follow_redirects=True)
    cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "kur.yaml")
    assert cfg.reel.target_duration_s == (30, 40)


def test_tempo_ve_muzik_kaydedilir(app):
    app.test_client().post("/channels/kur/edit-curated", data={
        "name": "Kür", "cut_pacing": "fast", "music_volume": "0.25",
    }, follow_redirects=True)
    cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "kur.yaml")
    assert cfg.reel.cut_pacing == "fast"
    assert cfg.reel.music_volume == 0.25


def test_seri_kaydedilir(app):
    app.test_client().post("/channels/kur/edit-curated", data={
        "name": "Kür", "series_enabled": "on", "series_title": "Mahalle Efsaneleri",
    }, follow_redirects=True)
    cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "kur.yaml")
    assert cfg.reel.series_enabled is True
    assert cfg.reel.series_title == "Mahalle Efsaneleri"


def test_montaj_alani_formda_yoksa_KORUNUR(app):
    """Sekmeli formda kullanıcı bir sekmeyi hiç açmayabilir; kaydetmek o
    sekmenin ayarlarını sıfırlamamalı."""
    app.test_client().post("/channels/kur/edit-curated",
                           data={"name": "Kür"}, follow_redirects=True)
    cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "kur.yaml")
    assert cfg.reel.target_duration_s == (45, 60)
    assert cfg.reel.cut_pacing == "medium"
    assert cfg.reel.music_volume == 0.12
