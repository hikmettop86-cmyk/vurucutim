"""Dört formatın düzenleme sayfası da ortak çekirdeği çizmeli.

ÖLÇÜM (2026-08-21, bu iş başlamadan önce):

    alan                    card/voiced  yorum  curated
    gizlilik                    var       YOK    YOK
    yükleme eşiği               var       YOK    YOK
    kategori                    var       YOK    YOK
    credentials_from            YOK       var    YOK

Kürate kanalda videonun gizliliği ve yükleme eşiği UI'den ayarlanamıyordu.
Kart kanalında bağlantı paylaştırılamıyordu — oysa `gundem` ile `gundem-yorum`
aynı YouTube kanalına üretiyor.
"""
from __future__ import annotations

import pytest

from short_bot.config import load_channel
from short_bot.formats import edit_path
from short_bot.web import create_app

_SETTINGS = (
    "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
    "web: {host: 127.0.0.1, port: 5005}\n"
    "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
)

_ORTAK = ("keywords: [a]\nlanguage: tr\nschedule_cron: '0 9 * * *'\n"
          "duration_s: 6\nmin_score: 6.0\nmax_candidates_per_run: 10\n"
          "template: newscast\n"
          "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
          "output_dir: out\nenabled: true\n")

KANALLAR = {
    "kart": "slug: kart\nname: Kart\nhandle: '@kart'\n" + _ORTAK,
    "sesli": ("slug: sesli\nname: Sesli\nhandle: '@sesli'\n" + _ORTAK
              + "voice: {enabled: true, voice_id: v1}\n"),
    "yorumk": ("slug: yorumk\nname: Yorum\nhandle: '@yorumk'\n" + _ORTAK
               + "content_source: trends\nvoice: {enabled: true, voice_id: v1}\n"),
    "kurate": ("slug: kurate\nname: Kürate\nhandle: '@kurate'\n" + _ORTAK
               + "content_source: curated\n"),
}


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    for slug, icerik in KANALLAR.items():
        (cfg_dir / "channels" / f"{slug}.yaml").write_text(icerik, encoding="utf-8")
    return create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates", music_root=tmp_path / "music",
        cache_dir=tmp_path / "cache", lock_dir=tmp_path / "locks",
        logs_dir=tmp_path / "logs", output_root=tmp_path / "out", scheduler=False)


def _url(app, slug):
    with app.app_context():
        cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml")
    return edit_path(cfg)


ORTAK_ALANLAR = ("yt_privacy_status", "yt_min_score_for_upload",
                 "yt_category_id", "yt_credentials_from", "yt_auto_upload")


@pytest.mark.parametrize("slug", list(KANALLAR))
@pytest.mark.parametrize("alan", ORTAK_ALANLAR)
def test_ortak_youtube_alanlari_her_formatta_cizilir(app, slug, alan):
    html = app.test_client().get(_url(app, slug), follow_redirects=True).get_data(as_text=True)
    assert f'name="{alan}"' in html, f"{slug} sayfasında {alan} yok"


@pytest.mark.parametrize("slug", list(KANALLAR))
def test_kimlik_ve_durum_her_formatta_cizilir(app, slug):
    html = app.test_client().get(_url(app, slug), follow_redirects=True).get_data(as_text=True)
    for alan in ("name", "handle", "archived", "enabled"):
        assert f'name="{alan}"' in html, f"{slug} sayfasında {alan} yok"


@pytest.mark.parametrize("slug", list(KANALLAR))
def test_gizlilik_kaydedilir(app, slug):
    """Alan çizilmek yetmez — POST tarafı da okumalı."""
    client = app.test_client()
    url = _url(app, slug)
    client.post(url, data={"name": "X", "yt_privacy_status": "unlisted",
                           "yt_min_score_for_upload": "7.5",
                           "yt_category_id": "25"}, follow_redirects=True)
    cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml")
    assert cfg.youtube is not None, f"{slug}: youtube bloğu hiç yazılmadı"
    assert cfg.youtube.privacy_status == "unlisted"
    assert cfg.youtube.min_score_for_upload == 7.5
    assert cfg.youtube.category_id == "25"


@pytest.mark.parametrize("slug", list(KANALLAR))
def test_pasife_alma_her_formatta_kaydedilir(app, slug):
    client = app.test_client()
    url = _url(app, slug)
    client.post(url, data={"name": "X", "archived": "1", "archived_present": "1",
                           "enabled_present": "1"}, follow_redirects=True)
    cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml")
    assert cfg.archived is True, f"{slug}: pasife alınamadı"
