"""Anlatım, KARTIN anlattığı olayı anlatmalı.

CANLI VAKA (2026-08-22, short 1772): kaynak makale "görünür sutyen modası"
hakkındaydı ve YAN CÜMLEDE ilgili bir film devamından söz ediyordu. Kart ana
haberi doğru özetledi (シドニー・スウィーニー / ブラジャー見せるファッション大流行),
anlatım ise EK KAYNAĞA kayıp 40 saniyenin tamamını film devamına ayırdı
(ライオンズゲート / ザハウスメイド). Yani ekran bir şey, ses başka şey söylüyordu.

İki yapısal sebep:
  1. Prompt ek kaynakları "same story" diye tanıtıyor — Google Trends bir
     trende 3 makale verir ve bunlar farklı açılar/olaylar olabilir.
  2. KART anlatım promptuna HİÇ geçmiyordu: kart ve anlatım aynı makaleden
     BAĞIMSIZ yazılıyor, hiçbir şey ikisini birbirine bağlamıyordu.
"""
from __future__ import annotations

import types

import pytest

from short_bot.config import ChannelConfig, VoiceConfig


def _kanal():
    return ChannelConfig(
        slug="t", name="T", keywords=[], language="ja", rss_locale="x",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, max_age_hours=24, template="flas",
        colors={"primary": "#d0021b", "accent": "#ffe600",
                "bg_gradient": ["#111111", "#222222"]},
        handle="@t", output_dir="o", enabled=False, content_source="trends",
        voice=VoiceConfig(enabled=True, provider="ai33", voice_id="v",
                          persona="p", target_duration_s=(30, 50)))


def _item():
    return types.SimpleNamespace(
        title="ブラジャー見せるファッションが大流行", description="",
        source="ハーパーズ バザー", link="https://x.test",
        trend_related=(), extra_links=(), trend_volume=20000,
        followup_of=None, trend_articles=())


KART = {"header_top": "シドニー・スウィーニー",
        "header_bottom": "ブラジャー見せるファッション大流行",
        "photo_overlay": "米スター女優28歳"}


def test_kart_prompta_capa_olarak_girer():
    from short_bot.narration_writer import build_yorum_prompt
    p = build_yorum_prompt(_item(), "gövde", _kanal(), extra_sources=[], card=KART)
    assert "シドニー・スウィーニー" in p
    assert "ブラジャー見せるファッション大流行" in p


def test_ek_kaynaklar_ayni_hikaye_diye_tanitilmaz():
    """Google Trends bir trende 3 makale verir; farklı olaylar olabilir."""
    from short_bot.narration_writer import build_yorum_prompt
    p = build_yorum_prompt(_item(), "gövde", _kanal(),
                           extra_sources=[("https://a.test/1", "başka bir olay")],
                           card=KART)
    assert "same story" not in p, "ek kaynaklar hâlâ aynı hikâye varsayılıyor"
    assert "MAIN STORY" in p or "ANA OLAY" in p


def test_kartsiz_cagri_hala_calisir():
    """Mevcut çağıranlar (kart geçmeyenler) kırılmamalı."""
    from short_bot.narration_writer import build_yorum_prompt
    p = build_yorum_prompt(_item(), "gövde", _kanal(), extra_sources=[])
    assert p


# --- uyum denetimi ------------------------------------------------------------

def test_kartin_oznesi_anlatimda_yoksa_uyumsuz():
    from short_bot.narration_writer import card_mismatch
    anlatim = "ライオンズゲートがザハウスメイドの続編製作を正式決定しました。"
    assert card_mismatch(anlatim, KART) is True


def test_kartin_oznesi_anlatimda_varsa_uyumlu():
    from short_bot.narration_writer import card_mismatch
    anlatim = "シドニー・スウィーニーさんも取り入れているこのファッションが広がっています。"
    assert card_mismatch(anlatim, KART) is False


def test_kart_yoksa_uyumsuzluk_iddia_edilmez():
    from short_bot.narration_writer import card_mismatch
    assert card_mismatch("herhangi bir metin", None) is False
    assert card_mismatch("herhangi bir metin", {}) is False


def test_cok_kisa_ozne_uyum_denetimine_girmez():
    """Tek karakterlik/çok kısa özne yanlış pozitif üretir."""
    from short_bot.narration_writer import card_mismatch
    assert card_mismatch("başka bir metin", {"header_top": "AB"}) is False


# --- parçalı eşleşme (yanlış pozitif) ------------------------------------------

def test_bilesik_ozne_parcayla_eslesir():
    """CANLI YANLIŞ POZİTİF (short 1777): kart öznesi 'M!LK塩﨑太智' (grup adı +
    kişi adı). Anlatım kişiyi anıyor ama grup önekini anmıyor; tam dizi
    aranınca 'sapmış' sayıldı."""
    from short_bot.narration_writer import card_mismatch
    anlatim = "小山リーナさんとの交際報道を受け、塩﨑太智さんが二年前に行った投稿が憶測を呼んでいます。"
    assert card_mismatch(anlatim, {"header_top": "M!LK塩﨑太智"}) is False


def test_gercek_sapma_hala_yakalanir():
    """short 1772: kart Sydney Sweeney, anlatım Lionsgate film devamı."""
    from short_bot.narration_writer import card_mismatch
    anlatim = ("ライオンズゲートによりザハウスメイドの続編製作が正式決定されました。"
               "キルスティンダンストやブリタニスノウら新たなキャストが加わります。")
    assert card_mismatch(anlatim, {"header_top": "シドニー・スウィーニー"}) is True


def test_latin_ozne_kelimeyle_eslesir():
    from short_bot.narration_writer import card_mismatch
    assert card_mismatch("Galatasaray transferi açıkladı.",
                         {"header_top": "GALATASARAY"}) is False


# --- Japonca kısaltma: yazı sistemi sınırı ------------------------------------
#
# CANLI YANLIŞ POZİTİF (short 1806, 2026-08-22): kart 「鹿島アントラーズ」,
# anlatım 「鹿島」 — Japon spor basınının standart kısaltması. Anlatım baştan
# sona konudaydı ama kapı "sapmış" dedi, İKİ düzeltme turu boşa gitti ve metin
# 179 karaktere düştü (bütçe tabanı 219). Yani yanlış pozitif hem tur hem süre
# kaybettiriyor.
#
# Japoncada bileşik ad neredeyse her zaman YAZI SİSTEMİ SINIRINDA kısalır:
#     鹿島アントラーズ → 鹿島   (kanji | katakana)
# Üstteki 3'lük kayan pencere bunu yakalayamaz: ortak parça 2 karakter.

def test_japon_kulubu_kisaltmayla_anilabilir():
    from short_bot.narration_writer import card_mismatch
    anlatim = ("鹿島は勢いよく飛ばせないと言われていましたが、現実には強かった。"
               "福岡を三対二で下し、十二シーズンぶりの開幕三連勝です。")
    assert card_mismatch(anlatim, {"header_top": "鹿島アントラーズ"}) is False


def test_yazi_kosulari_sinirda_boler():
    from short_bot.narration_writer import _yazi_kosulari
    assert _yazi_kosulari("鹿島アントラーズ") == ["鹿島", "アントラーズ"]
    assert _yazi_kosulari("浦和レッズ") == ["浦和", "レッズ"]
    assert _yazi_kosulari("M!LK塩﨑太智") == ["M", "LK", "塩﨑太智"]


@pytest.mark.parametrize("ozne,anlatim", [
    ("ソフトバンクホークス", "ソフトバンクの大津亮介が十勝目を挙げました。"),
    ("横浜FCマリノス", "横浜は開幕戦で勝ち点を落としました。"),
])
def test_baska_kulup_kisaltmalari_da_gecer(ozne, anlatim):
    from short_bot.narration_writer import card_mismatch
    assert card_mismatch(anlatim, {"header_top": ozne}) is False


# --- gevşetme GERÇEK sapmayı kaçırmamalı --------------------------------------

def test_alakasiz_anlatim_hala_sapmis_sayilir():
    from short_bot.narration_writer import card_mismatch
    assert card_mismatch("全く別の話題です。天気の話をしましょう。",
                         {"header_top": "鹿島アントラーズ"}) is True


def test_1772_sapmasi_hala_yakalanir():
    """Bu gevşetme, kapının var oluş sebebini bozmamalı."""
    from short_bot.narration_writer import card_mismatch
    anlatim = ("ライオンズゲートによりザハウスメイドの続編製作が正式決定されました。"
               "キルスティンダンストやブリタニスノウら新たなキャストが加わります。")
    assert card_mismatch(anlatim, {"header_top": "シドニー・スウィーニー"}) is True


def test_tek_karakterlik_kosu_eslesme_saymaz():
    """2 karakter tabanı: tek karakterlik koşu rastgele eşleşir."""
    from short_bot.narration_writer import card_mismatch
    # 'A' tek karakterlik latin koşusu; anlatımda A geçse bile uyumlu sayılmamalı.
    assert card_mismatch("Aさんは全く別の出来事について話しました。",
                         {"header_top": "A・ロドリゲス"}) is True
