"""Ortak çekirdek alanları: TEK okuyucu, TEK partial kümesi.

Bu testlerin varlık sebebi ölçülmüş bir hata sınıfı: ortak alanlar dört düzenleme
sayfasında ayrı ayrı yazılmıştı ve dördü de eksikti —

    alan                    card/voiced  yorum  curated  reel
    gizlilik                    var       YOK    YOK      var
    yükleme eşiği               var       YOK    YOK      var
    kategori · AI etiketi       var       YOK    YOK      kısmi
    credentials_from            YOK       var    YOK      YOK

Kürate kanalda videonun gizliliği UI'den ayarlanamıyordu; kart kanalında da
bağlantı paylaştırılamıyordu — oysa gundem ile gundem-yorum aynı YouTube
kanalına üretiyor.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from short_bot.config import ChannelConfig, YoutubeChannelConfig


def _cfg(**kw) -> ChannelConfig:
    base = dict(
        slug="ch", name="C", keywords=["a"], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="newscast",
        colors={"primary": "#000", "accent": "#111",
                "bg_gradient": ["#000", "#111"]},
        handle="@ch", output_dir="out", enabled=True, language="tr",
    )
    base.update(kw)
    return ChannelConfig(**base)


# --- read: form → dataclasses.replace kwargs ------------------------------

def test_ortak_alanlar_okunur():
    from short_bot.web.core_fields import core_updates
    upd = core_updates({
        "name": "Yeni Ad", "handle": "@yeni", "enabled": "1",
        "schedule_cron": "0 8 * * *",
        "yt_auto_upload": "1", "yt_privacy_status": "unlisted",
        "yt_category_id": "28", "yt_min_score_for_upload": "7.5",
    }, _cfg())
    assert upd["name"] == "Yeni Ad"
    assert upd["handle"] == "@yeni"
    assert upd["enabled"] is True
    assert upd["schedule_cron"] == "0 8 * * *"
    yt = upd["youtube"]
    assert yt.auto_upload is True
    assert yt.privacy_status == "unlisted"
    assert yt.category_id == "28"
    assert yt.min_score_for_upload == 7.5


def test_formda_olmayan_alan_KORUNUR():
    """Kısmi form mevcut ayarı silmemeli.

    Gündem Yorum formunda `schedule_cron` yok (runs_per_day'den türetiliyor);
    o formu kaydetmek kanalın cron'unu sıfırlamamalı."""
    from short_bot.web.core_fields import core_updates
    eski = _cfg(schedule_cron="0 3,15 * * *",
                youtube=YoutubeChannelConfig(privacy_status="private",
                                             category_id="17"))
    upd = core_updates({"name": "C"}, eski)
    # "dokunmamak" = anahtarı hiç koymamak. replace(**upd) mevcut değeri korur.
    assert "schedule_cron" not in upd
    assert "youtube" not in upd
    assert "enabled" not in upd
    import dataclasses
    yeni = dataclasses.replace(eski, **upd)
    assert yeni.schedule_cron == "0 3,15 * * *"
    assert yeni.youtube.privacy_status == "private"
    assert yeni.youtube.category_id == "17"


def test_archived_ayri_eksen_olarak_okunur():
    """enabled = cron çalışsın mı; archived = Kokpit'te görünsün mü. İkisi ayrı."""
    from short_bot.web.core_fields import core_updates
    upd = core_updates({"enabled": "1", "archived": "1"}, _cfg())
    assert upd["enabled"] is True
    assert upd["archived"] is True


def test_credentials_from_bos_veya_kendi_slug_None_olur():
    from short_bot.web.core_fields import core_updates
    c = _cfg(youtube=YoutubeChannelConfig(credentials_from="gundem"))
    assert core_updates({"yt_credentials_from": ""}, c)["youtube"].credentials_from is None
    assert core_updates({"yt_credentials_from": "ch"}, c)["youtube"].credentials_from is None
    assert core_updates({"yt_credentials_from": "gundem"},
                        c)["youtube"].credentials_from == "gundem"


def test_credentials_from_form_da_YOKSA_silinmez():
    """CANLI VAKA (2026-08-20): açılırda seçenek yokken tarayıcı boş değer
    gönderdi ve deutschland-klartext'in bağlantı paylaşımı SESSİZCE silindi."""
    from short_bot.web.core_fields import core_updates
    import dataclasses
    c = _cfg(youtube=YoutubeChannelConfig(credentials_from="gundem"))
    upd = core_updates({"name": "C"}, c)
    assert "youtube" not in upd
    assert dataclasses.replace(c, **upd).youtube.credentials_from == "gundem"


def test_credentials_from_baska_yt_alani_varken_de_silinmez():
    """Asıl tuzak: formda BAŞKA yt alanı var (blok güncelleniyor) ama
    `yt_credentials_from` yok. Blok yeniden kurulurken bağlantı düşmemeli."""
    from short_bot.web.core_fields import core_updates
    c = _cfg(youtube=YoutubeChannelConfig(credentials_from="gundem"))
    upd = core_updates({"yt_auto_upload": "1"}, c)
    assert upd["youtube"].auto_upload is True
    assert upd["youtube"].credentials_from == "gundem"


# --- context: GET için linkable listesi ------------------------------------

def test_linkable_secili_ama_baglanmamis_degeri_de_tasir(tmp_path):
    """Seçili değer listede yoksa açılır onu göstermez, kaydetmek ayarı siler."""
    from short_bot.web.core_fields import linkable_channels
    others = [_cfg(slug="gundem", name="Gündem"), _cfg(slug="baska", name="Başka")]
    liste = linkable_channels(
        _cfg(slug="ch", youtube=YoutubeChannelConfig(credentials_from="gundem")),
        others=others,
        has_credentials=lambda s: False,       # HİÇBİRİ bağlı değil
        channel_info=lambda s: None)
    assert [l["slug"] for l in liste] == ["gundem"]
    assert liste[0]["connected"] is False


def test_linkable_kendini_listelemez(tmp_path):
    from short_bot.web.core_fields import linkable_channels
    others = [_cfg(slug="ch", name="C"), _cfg(slug="gundem", name="Gündem")]
    liste = linkable_channels(_cfg(slug="ch"), others=others,
                              has_credentials=lambda s: True,
                              channel_info=lambda s: None)
    assert [l["slug"] for l in liste] == ["gundem"]
