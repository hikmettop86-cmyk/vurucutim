"""Olgu kapısı CJK'de KÖRDÜ — kısmen görür hale getirilir.

ÖLÇÜLDÜ (2026-08-22, Japonca kanalın ilk gerçek koşusu):

    _proper_nouns(japonca_metin) -> []      (büyük harf yok)
    _SAYI.findall(japonca_metin) -> []      (sayılar kanji: 五百億)
    unverified_claims("ソニーが五百億円で買収しました", "布施博 破産") -> []

Yani anlatım ne uydurursa uydursun kapı "temiz" diyordu ve log da öyle
yazıyordu — sessiz değil, YANILTICI bir güvence.

KAPSAM DÜRÜSTLÜĞÜ: bu düzeltme sayıları (rakam + kanji) ve Latin dizilerini
görür hale getirir. Katakana BİLEREK dışarıda: Japoncada katakana yalnız özel
isim değil her ödünç sözcüktür (プラットフォーム, メディア) ve onu aday saymak
kapıyı yanlış pozitife boğar — kodun kendi dersi (Burhan vakası: yanlış pozitif
iki turu da reddettirip videoyu hiç ürettirmedi).

Kanji-only Japon isimleri (布施博) morfolojik çözümleyici olmadan güvenilir
çıkarılamaz; bu kapı onları GÖRMEZ ve görüyormuş gibi de yapmaz.
"""
from __future__ import annotations

KAYNAK_JA = "俳優の布施博さんが社長を務める芸能プロダクションが破産開始決定を受けました。"


def test_kanji_sayi_uydurmasi_yakalanir():
    from short_bot.fact_gate import unverified_claims
    eksik = unverified_claims("負債は五百億円にのぼります。", KAYNAK_JA, language="ja")
    assert eksik, "kaynakta olmayan kanji sayı yakalanmadı"


def test_rakam_uydurmasi_yakalanir():
    from short_bot.fact_gate import unverified_claims
    eksik = unverified_claims("負債は42億円です。", KAYNAK_JA, language="ja")
    assert any("42" in e for e in eksik)


def test_latin_kisaltma_uydurmasi_yakalanir():
    from short_bot.fact_gate import unverified_claims
    eksik = unverified_claims("NHKが報じました。", KAYNAK_JA, language="ja")
    assert any("NHK" in e for e in eksik)


def test_kaynakta_gecen_sayi_yakalanmaz():
    from short_bot.fact_gate import unverified_claims
    kaynak = "負債総額は五百億円です。"
    assert unverified_claims("負債は五百億円にのぼります。", kaynak, language="ja") == []


def test_odunc_sozcukler_yanlis_pozitif_uretmez():
    """プラットフォーム / メディア özel isim DEĞİL — kapıyı boğmamalı."""
    from short_bot.fact_gate import unverified_claims
    metin = "配信プラットフォームの普及やメディアの多様化で構造が変わりました。"
    assert unverified_claims(metin, KAYNAK_JA, language="ja") == []


def test_tek_kanji_sayi_yanlis_pozitif_uretmez():
    """一部 / 一般 gibi sözcüklerdeki tek kanji rakam aday OLMAMALI."""
    from short_bot.fact_gate import unverified_claims
    assert unverified_claims("一部の関係者は一般的な見方を示しています。",
                             KAYNAK_JA, language="ja") == []


def test_turkce_davranisi_degismedi():
    from short_bot.fact_gate import unverified_claims
    # Cümle BAŞINDAKİ kelime aday değil (belgelenmiş kural, Burhan vakası) —
    # Sony bilerek cümle içinde.
    eksik = unverified_claims("Şirketi Sony 500 milyona satın aldı.",
                              "Barikiya iflas etti.", language="tr")
    assert "Sony" in eksik and "500" in eksik
