"""Marka güvenliği süzgeci: neredeyse kesin para kazandırmayan konuları eler.

ÖLÇÜLDÜ (2026-08-22, canlı havuzlar):

  JP/magazin (48 aday): 「ブラジャーをあえて見せる」ファッション, 密会強要疑惑…
  DE/adalet (31 aday): stark verwest - zwei Tote, Bulle enthauptet, Japan
                       richtet Mörder hin…

KRİTİK AYRIM: `adalet` dikeyinde şiddet ve ölüm İÇERİĞİN KENDİSİDİR. Hepsini
elemek dikeyi öldürür. YouTube'un kuralı da öyle değil: sıradan suç haberi
(gözaltı, dava, kaza) sınırlı reklamla geçer, GRAFİK DETAY geçmez.

Bu yüzden süzgeç yalnız neredeyse kesin para kazandırmayan sınıfları eler:
cinsel içerik, grafik ceset/uzuv detayı, intihar, çocuk istismarı, idam,
hayvana eziyet, uyuşturucu. Sıradan suç haberi ELENMEZ.
"""
from __future__ import annotations

import pytest


# --- elenmesi gerekenler ------------------------------------------------------

@pytest.mark.parametrize("baslik,dil", [
    ("「ブラジャーをあえて見せる」ファッションがアメリカで大流行", "ja"),
    ("Siegen: Bereits stark verwest - Polizei findet zwei Tote", "de"),
    ("Bulle auf Koppel enthauptet: grausiger Fund bei Rostock", "de"),
    ("Tödlicher Brandanschlag 2009: Japan richtet Mörder hin", "de"),
    ("Ünlü oyuncunun uyuşturucu testi pozitif çıktı", "tr"),
])
def test_yuksek_riskli_elenir(baslik, dil):
    from short_bot.brand_safety import risk_of
    assert risk_of(baslik, "", language=dil) is not None, baslik


# --- elenmemesi gerekenler (dikeyin ta kendisi) -------------------------------

@pytest.mark.parametrize("baslik,dil", [
    ("Isernhagen: 84-Jährige stirbt nach Raubüberfall in ihrem Haus", "de"),
    ("Mutter von Drillingen getötet: Ehemann legt Geständnis ab", "de"),
    ("Angriff während der Kommunion: Haftstrafe für Priester-Attentäter", "de"),
    ("35-jährige Ceylan Sabrina Müller vermisst", "de"),
    ("藤井風 12月のタイ公演中止を発表", "ja"),
    ("RIIZE冠バラエティー シーズン2決定", "ja"),
    ("Altın rekor kırdı, gram fiyatı 7 bin lirayı aştı", "tr"),
    ("61 yıllık şirket iflas etti", "tr"),
])
def test_siradan_haber_elenmez(baslik, dil):
    from short_bot.brand_safety import risk_of
    assert risk_of(baslik, "", language=dil) is None, baslik


# --- seviyeler ----------------------------------------------------------------

def test_kapali_seviyede_hicbir_sey_elenmez():
    from short_bot.brand_safety import risk_of
    assert risk_of("ブラジャー見せるファッション", "", language="ja", level="off") is None


def test_siki_seviye_sinirdakileri_de_eler():
    """'超ミニスカ' Japon TV dilinde sıradan ama beden odaklı — normalde geçer,
    sıkı seviyede elenir."""
    from short_bot.brand_safety import risk_of
    b = "井桁弘恵、超ミニスカ姿披露も「心配になるレベル」細すぎスタイル"
    assert risk_of(b, "", language="ja") is None
    assert risk_of(b, "", language="ja", level="strict") is not None


def test_gecersiz_seviye_sessizce_gecmez():
    from short_bot.brand_safety import risk_of
    with pytest.raises(ValueError):
        risk_of("x", "", language="tr", level="yok-boyle-bir-seviye")


# --- gövde metni de taranır ----------------------------------------------------

def test_govdedeki_risk_de_yakalanir():
    from short_bot.brand_safety import risk_of
    assert risk_of("Sıradan bir başlık", "Olayda kurbanın cesedi parçalanmış halde bulundu.",
                   language="tr") is not None


def test_bilinmeyen_dilde_susulur():
    """Kalıbı olmayan dilde uydurma yasak koymaktansa hiç koymamak yeğdir."""
    from short_bot.brand_safety import risk_of
    assert risk_of("anything at all", "", language="ko") is None
