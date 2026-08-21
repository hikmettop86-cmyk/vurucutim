"""Yorum/anlatım bütçesi CJK'de KARAKTERLE ölçülmeli.

BULGU (2026-08-22, Japonca kanal kurulurken): `narration_writer.word_budget`
yalnız kelime biliyor ve `Narration.word_count()` `.split()` sayıyor. Japoncada
boşluk yok:

    len("まず、藤井風さんが…") = 65 karakter
    "まず、藤井風さんが…".split() -> 1 parça

Sonuç: Japonca kanala "66-110 kelime" bütçesi kuruluyor, sayım 1 dönüyor,
kontrol hep başarısız, bir "UZAT" turu koşuyor ve metin bütçeden bağımsız
kabul ediliyor. Yani bütçe HİÇ çalışmıyor; video süresi rastgele.

Doğru mekanizma zaten kodda: reel_narration.budget_unit / reel_word_budget
(kürate yolu için çözülmüş, yorum yoluna hiç gelmemiş).

Ölçüm (2026-08-22, ai33 Japonca sesler, speed 1.05): 166 karakter -> 26,5-28,7
sn, yani 5,8-6,3 karakter/sn. Kodda yazılı 5,49 daha yavaş, yani daha güvenli
(bütçe küçük kalır, video hedefi AŞMAZ) — kodun kendi kuralı bu.
"""
from __future__ import annotations

JA = ("まず、藤井風さんが十二月に予定していたタイ公演の中止を発表しました。"
      "所属事務所によると、現地の運営体制の都合が理由とされています。")
TR = "Bakın, altın bu sabah yeni bir rekor kırdı ve gram fiyatı yedi bin lirayı aştı."


def test_japonca_butce_karakterle_kurulur():
    from short_bot.narration_writer import word_budget
    lo, hi = word_budget((30, 50), "ja")
    # 30-50 sn x ~5,49 karakter/sn
    assert 150 <= lo <= 180, f"alt sınır karakter bütçesi değil: {lo}"
    assert 250 <= hi <= 300, f"üst sınır karakter bütçesi değil: {hi}"


def test_turkce_butce_kelimeyle_kalir():
    """Mevcut dillerin davranışı bit bit korunmalı."""
    from short_bot.narration_writer import word_budget
    assert word_budget((30, 50), "tr") == (59, 99)


def test_ispanyolca_butce_degismedi():
    from short_bot.narration_writer import word_budget
    assert word_budget((30, 50), "es") == (79, 132)


def test_japonca_uzunluk_karakterle_sayilir():
    from short_bot.narration_writer import narration_length
    n = narration_length(JA, "ja")
    assert n > 50, f"Japonca uzunluk kelime sayılmış: {n}"
    assert n == len(JA.replace(" ", ""))


def test_turkce_uzunluk_kelimeyle_sayilir():
    from short_bot.narration_writer import narration_length
    assert narration_length(TR, "tr") == len(TR.split())


def test_japonca_metin_butceye_oturuyor():
    """Gerçek ölçüm: 166 karakter -> 28 sn. Bütçe bunu KABUL etmeli."""
    from short_bot.narration_writer import word_budget
    lo, hi = word_budget((30, 50), "ja")
    assert lo <= 200 <= hi, "30-50 sn'lik gerçekçi bir metin bütçe dışında kalıyor"


def test_geri_bildirim_birimi_dile_gore():
    """'previous attempt had 1 spoken words' Japoncada anlamsız bir talimat."""
    from short_bot.narration_writer import _budget_feedback
    ja = _budget_feedback(80, 164, 274, language="ja")
    assert "character" in ja.lower()
    tr = _budget_feedback(20, 59, 99, language="tr")
    assert "word" in tr.lower()
