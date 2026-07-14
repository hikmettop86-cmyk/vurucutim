"""Dile duyarlı normalleştirme.

ÖLÇÜLDÜ (düzeltmeden ÖNCE, gerçek kodla):
    _fold("Ich zeige euch")                  -> "ıch zeige euch"   (I -> ı)
    re.search(r"\\bich\\b", ...)               -> None
    turkish_upper("Bier Garten")             -> "BİER GARTEN"      (noktalı İ)
    strip_non_turkish_diacritics("Täglich")  -> "Taglich"          (ä silindi)

Yani kusursuz bir Almanca yasaklı-kalıp listesi yazsak bile ASLA eşleşmezdi; ve
Almanca anlatım metni model sınırında sessizce bozuluyordu.

Sonuncusu en ağırı: strip_non_turkish_diacritics bir pydantic field_validator,
yani LLM'in yazdığı HER anlatım cümlesinde koşuyor. TTS yanlış okuyor, altyazıda
yanlış görünüyor — ve hiçbir hata, hiçbir log.
"""
import re

from short_bot.locale import ALPHABET_EXTRA, SUPPORTED_LANGUAGES
from short_bot.text_normalize import (language, locale_fold, locale_upper,
                                      strip_foreign_diacritics, turkish_upper)


# --- ALFABE TABLOSU --------------------------------------------------------

def test_her_desteklenen_dilin_alfabesi_TANIMLI():
    for lang in SUPPORTED_LANGUAGES:
        assert lang in ALPHABET_EXTRA, f"{lang} alfabesi tanımsız"


def test_almanca_alfabesi_ESZET_icerir():
    # Sonnet'e bıraksaydık 'ß'i unutabilirdi ve Almanca anlatım sessizce bozulurdu
    # ("Weiß" → "Wei"). Bu yüzden alfabe OLGU tablosu, LLM üretimi değil.
    for ch in "äöüßÄÖÜ":
        assert ch in ALPHABET_EXTRA["de"], ch


def test_turkce_alfabesi_bugunku_KEEP_setiyle_ayni():
    # Eski _TURKISH_KEEP = set("ÇĞİıÖŞÜçğöşü") — birebir korunmalı, yoksa Türkçe
    # kanalların çıktısı değişir.
    assert set(ALPHABET_EXTRA["tr"]) == set("ÇĞİıÖŞÜçğöşü")


# --- KÜÇÜLTME (locale_fold) ------------------------------------------------

def test_turkce_fold_BUGUNKU_davranis():
    # 'İ'.lower() birleşik nokta üretir (i̇) ve kelimeyi eşleşmez kılar; elle eşliyoruz.
    assert locale_fold("İSTANBUL", "tr") == "istanbul"
    assert locale_fold("IŞIK", "tr") == "ışık"


def test_almanca_fold_I_harfini_BOZMAZ():
    """GERÇEK HATA: _fold Türkçe için I->ı yapıyordu, Almanca 'Ich' -> 'ıch' oluyordu
    ve r'\\bich\\b' asla eşleşmiyordu. Denetçi çalışıyor görünüp sıfır şey buluyordu."""
    assert locale_fold("Ich", "de") == "ich"
    assert re.search(r"\bich\b", locale_fold("Ich zeige euch", "de"))


def test_fold_varsayilani_TURKCE():
    # Mevcut çağıranlar dil geçirmiyor; davranışları değişmemeli.
    assert locale_fold("IŞIK") == "ışık"


# --- BÜYÜTME (locale_upper) ------------------------------------------------

def test_turkce_upper_NOKTALI_I():
    assert locale_upper("Bilinmeyen Tarih", "tr") == "BİLİNMEYEN TARİH"
    assert locale_upper("Bilinmeyen Tarih", "tr") == turkish_upper("Bilinmeyen Tarih")


def test_almanca_upper_NOKTASIZ_I():
    """EKRANDA GÖRÜNÜR: Almanca kanalın rozeti 'BİER GARTEN' yazıyordu. Rozet, kanalın
    özenli olduğunu SÖYLEMESİ gereken şeydir."""
    assert locale_upper("Bier Garten", "de") == "BIER GARTEN"


# --- AKSAN KORUMASI (strip_foreign_diacritics) -----------------------------

def test_turkce_YABANCI_aksani_siler():
    # Var oluş sebebi: model Türkçe çıktıya İspanyolca/Fransızca aksan sızdırıyor.
    with language("tr"):
        assert strip_foreign_diacritics("CANLÍ") == "CANLI"
        assert strip_foreign_diacritics("español") == "espanol"
        assert strip_foreign_diacritics("café") == "cafe"
        assert strip_foreign_diacritics("Çocuklar") == "Çocuklar"   # Türkçe: korunur
        assert strip_foreign_diacritics("İPLER") == "İPLER"


def test_almanca_KENDI_harflerini_korur():
    """EN AĞIR SESSİZ HATA: 'Täglich' -> 'Taglich'. Bu bir pydantic field_validator,
    yani LLM'in yazdığı her anlatım cümlesinde koşuyordu."""
    with language("de"):
        assert strip_foreign_diacritics("Täglich frisches Bier") == "Täglich frisches Bier"
        assert strip_foreign_diacritics("Weiß") == "Weiß"
        assert strip_foreign_diacritics("Öl") == "Öl"
        # Almanca alfabesinde OLMAYAN aksan yine silinir:
        assert strip_foreign_diacritics("café") == "cafe"


def test_ispanyolca_kendi_harflerini_korur():
    with language("es"):
        assert strip_foreign_diacritics("español") == "español"
        assert strip_foreign_diacritics("¿Sabías?") == "¿Sabías?"


def test_fransizca_kendi_harflerini_korur():
    with language("fr"):
        assert strip_foreign_diacritics("café à côté") == "café à côté"
        assert strip_foreign_diacritics("cœur") == "cœur"


def test_dil_kurulmazsa_TURKCE_varsayilan():
    # Bugünkü davranış: contextvar'ın varsayılanı "tr". Regresyon kalkanı.
    assert strip_foreign_diacritics("español") == "espanol"


def test_language_blogu_KAPSAMI_sinirlar():
    with language("de"):
        assert strip_foreign_diacritics("Täglich") == "Täglich"
    # Blok bitince eski dile döner — sızıntı yok.
    assert strip_foreign_diacritics("Täglich") == "Taglich"


def test_language_blogu_IC_ICE():
    with language("de"):
        with language("es"):
            assert strip_foreign_diacritics("español") == "español"
        # İç blok bitti, dış blok hâlâ Almanca:
        assert strip_foreign_diacritics("Täglich") == "Täglich"


def test_eski_ad_TAKMA_AD_olarak_calisir():
    """15 import noktası var (models.py, narration.py, reel_models.py, ...); kırmıyoruz."""
    from short_bot.text_normalize import strip_non_turkish_diacritics
    assert strip_non_turkish_diacritics("CANLÍ") == "CANLI"
