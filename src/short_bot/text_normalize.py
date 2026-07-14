"""Dile duyarlı metin normalleştirme: aksan koruması, büyütme, küçültme.

Üç iş var ve ÜÇÜ DE DİLE ÖZGÜ. Dile duyarsız hâlleri Türkçe dışındaki her kanalı
SESSİZCE bozuyordu:

  • strip_foreign_diacritics — hedef dilin alfabesinde olmayan aksanları söker.
    Dile duyarsız hâli Almanca 'Täglich'i 'Taglich' yapıyordu. Bu bir pydantic
    field_validator, yani LLM'in yazdığı HER anlatım cümlesinde koşuyor: TTS yanlış
    okuyor, altyazıda yanlış görünüyor. Hiçbir hata, hiçbir log.

  • locale_upper — Türkçede 'i'nin büyüğü 'İ'dir, Almancada 'I'dır. Dile duyarsız hâli
    Almanca kanalın ekran rozetine 'BİER GARTEN' yazıyordu.

  • locale_fold — eşleştirme için küçültme. Türkçe eşlemesi 'I' → 'ı' yapıyor; Almanca
    metinde bu 'Ich'i 'ıch' yapar ve r'\\bich\\b' ASLA eşleşmez. Yani kusursuz bir
    Almanca yasaklı-kalıp listesi yazsak bile denetçi sıfır şey bulurdu.
"""
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar

from short_bot.locale import ALPHABET_EXTRA

# Aktif hedef dil.
#
# NEDEN CONTEXTVAR, NEDEN PARAMETRE DEĞİL: aksan temizleyicisi bir pydantic
# field_validator'dan çağrılıyor ve validator'ın çağıranın dilini görmesinin yolu yok.
# Dili her model kurulum noktasından (LLM parse + fit_word_budget gibi yeniden-kurma
# yolları + testler) elle geçirmek onlarca dokunuş demek ve BİRİ UNUTULURSA SESSİZCE
# TÜRKÇEYE DÜŞER — düzeltmeye çalıştığımız hatanın aynısı. Contextvar iş parçacığı
# başına yalıtık (her pipeline koşusu kendi thread'inde) ve `with language(...)`
# kapsamı açıkça sınırlar.
_LANG: ContextVar[str] = ContextVar("shortbot_lang", default="tr")


@contextmanager
def language(lang: str):
    """Bu blok boyunca hedef dil ``lang``. İç içe kullanılabilir."""
    tok = _LANG.set(lang)
    try:
        yield
    finally:
        _LANG.reset(tok)


def current_language() -> str:
    """Şu anki hedef dil (kurulmadıysa 'tr')."""
    return _LANG.get()


def strip_foreign_diacritics(s: str) -> str:
    """Hedef dilin alfabesinde OLMAYAN harflerin aksanını sök.

    Var oluş sebebi: model ara sıra hedef dile yabancı aksan sızdırıyor (Türkçe
    çıktıda 'CANLÍ'). Ama sökme HEDEF DİLE GÖRE yapılmalı — Almancada 'ä' yabancı
    değil, alfabenin harfidir.

        with language("tr"): strip_foreign_diacritics("CANLÍ")    → "CANLI"
        with language("de"): strip_foreign_diacritics("Täglich")  → "Täglich"
        with language("tr"): strip_foreign_diacritics("Täglich")  → "Taglich"
    """
    keep = ALPHABET_EXTRA.get(_LANG.get(), ALPHABET_EXTRA["tr"])
    out = []
    for ch in s:
        if ord(ch) < 128 or ch in keep:
            out.append(ch)
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomposed if not unicodedata.combining(c))
        out.append(base if base else "")
    return "".join(out)


# Eski ad — 15 import noktası var (models.py, narration.py, generator.py,
# reel_models.py, reel_arc.py). Kırmıyoruz; varsayılan dil "tr" olduğu için davranış
# birebir aynı kalır.
strip_non_turkish_diacritics = strip_foreign_diacritics


# Python'un str.upper()'ı Unicode'un DİLDEN BAĞIMSIZ eşlemesini kullanır: 'i' → 'I'.
# Türkçede 'i'nin büyüğü 'İ'dir (noktalı), 'ı'nın büyüğü 'I'dır (noktasız). Bu iki
# harf Türkçede AYRI harflerdir; karıştırmak kelimeyi bozar.
_TR_UPPER = str.maketrans({"i": "İ", "ı": "I"})


def turkish_upper(s: str) -> str:
    """Türkçe-farkında büyük harf.

    'Bilinmeyen Tarih'.upper() → 'BILINMEYEN TARIH' (YANLIŞ)
    turkish_upper('Bilinmeyen Tarih') → 'BİLİNMEYEN TARİH' (doğru)

    Bunun en çok acıttığı yer MARKA ROZETİDİR: rozet, kanalın özenli olduğunu
    söylemesi gereken şeydir; 'BILINMEYEN TARIH' yazan bir rozet tam tersini ilan
    eder.
    """
    return s.translate(_TR_UPPER).upper()


def locale_upper(s: str, lang: str = "tr") -> str:
    """Dile duyarlı büyük harf.

    Türkçe eşlemesini Almancaya uygulamak da en az onun kadar yanlıştır:
    'Bier Garten' → 'BİER GARTEN'. Büyütme dile özgüdür.
    """
    return turkish_upper(s) if lang == "tr" else s.upper()


def locale_fold(text: str, lang: str = "tr") -> str:
    """Eşleştirme için küçültme (kalıp denetimi, kelime karşılaştırması).

    Türkçe: ``"İ".lower()`` birleşik nokta üretir (i̇) ve kelimeyi eşleşmez kılar;
    harfleri elle eşliyoruz. Ama bu eşleme DİLE ÖZGÜ: Almancada 'I' harfinin küçüğü
    'ı' değil 'i'dir. Dile duyarsız hâli 'Ich'i 'ıch' yapıyordu ve r'\\bich\\b' asla
    eşleşmiyordu — denetçi çalışıyor görünüp sıfır şey buluyordu.
    """
    if lang == "tr":
        return text.replace("İ", "i").replace("I", "ı").lower()
    return text.casefold()
