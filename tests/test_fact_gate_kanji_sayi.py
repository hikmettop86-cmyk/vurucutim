"""Kanji sayı ile rakam AYNI olguyu gösterir — kapı ikisini eşleştirmeli.

CANLI VAKA (2026-08-22, ikinci Japonca koşu): kapı '二十一' (=21) iddiasını
"kaynakta yok" diye reddetti ve İKİ denemede de düzelmeyince ÜRETİM DURDU.
Oysa kaynakta 21 vardı — sadece rakamla yazılmıştı.

Bu, kodun kendi uyardığı yanlış-pozitif sınıfı (Burhan vakası): anlatım TTS
için sayıyı okunduğu gibi yazar, haber metni rakam kullanır.
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("kanji,deger", [
    ("二十一", 21), ("十二", 12), ("五百億", 50_000_000_000),
    ("三千", 3000), ("四十", 40), ("百", 100),
])
def test_kanji_sayi_degeri(kanji, deger):
    from short_bot.fact_gate import kanji_sayi_degeri
    assert kanji_sayi_degeri(kanji) == deger


def test_kaynakta_rakamla_gecen_sayi_uydurma_sayilmaz():
    from short_bot.fact_gate import unverified_claims
    assert unverified_claims("二十一日に決定しました。", "21日に決定を受けました。",
                             language="ja") == []


def test_gercekten_uydurma_sayi_hala_yakalanir():
    from short_bot.fact_gate import unverified_claims
    eksik = unverified_claims("五百億円の負債です。", "21日に決定を受けました。",
                              language="ja")
    assert eksik, "kaynakta hiç geçmeyen sayı kaçtı"


def test_kaynakta_kanji_anlatimda_rakam_da_eslesir():
    from short_bot.fact_gate import unverified_claims
    assert unverified_claims("21日に決定しました。", "二十一日に決定を受けました。",
                             language="ja") == []
