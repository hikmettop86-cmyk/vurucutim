"""Anlatım kapısı: dayanaksız kısa cümleyi yakalar.

GERÇEK VAKA (2026-08-20, kullanıcı bildirdi). Şu anlatımda:

    "… Hayati tehlikeyi atlattı, yoğun bakımda. **Asıl mesele hız.** Saldırgan bir ay
     önce CHP'nin ilçe başkanlığından istifa edip aynı partiye geçmişti. …"

"Asıl mesele hız." cümlesi DİLBİLGİSİ olarak kusursuz (Türkçede ad cümlesi, ek-fiil
düşmüş). Kusur BAĞLAMDA: "hız" o an neyin hızı, dinleyici bilmiyor — açıklaması iki
cümle sonra geliyor. Seslendirmede geri sarma yok; boşta kalan soyut cümle "yapay zekâ
yazmış" hissi veren şeylerin başında.

Kaynağı prompt'un kendisiydi: "vary sentence length" kuralı modeli kısa, telgraf gibi
başlık cümleleri kurmaya itiyor ve beat'lerin ekran kartı üslubu (ALL-CAPS 2-5 kelime)
konuşulan metne sızıyor.

Kural yetmediğine göre kapı MEKANİK (fact_gate'in felsefesi). Ama fact_gate'ten farkı:
bu bir ÜSLUP kusuru, uydurma bilgi değil — bir düzeltme turu istenir, ısrar ederse video
yine üretilir (log'a düşer). Uydurma bilgi videoyu düşürür, kötü cümle düşürmez.
"""
from __future__ import annotations

import re

from short_bot.text_normalize import locale_fold

# Somut karşılığı olmayan "başlık" kelimeleri: cümlede bunlardan biri varsa ve
# cümle kısa + dayanaksızsa (özel ad/sayı yok) okuyucu neyin kastedildiğini bilemez.
_META_WORDS: frozenset[str] = frozenset("""
asil mesele sorun soru konu nokta durum gercek onemli kritik ilginc tablo denklem
hikaye hesap dengeler sonuc ozet anahtar sir formul cevap
""".split())

# Sayı: rakam ya da yazıyla (anlatımda sayılar yazıyla okunur)
_NUM_WORDS: frozenset[str] = frozenset("""
bir iki uc dort bes alti yedi sekiz dokuz on yirmi otuz kirk elli altmis yetmis
seksen doksan yuz bin milyon milyar yarim ceyrek ilk son birinci ikinci ucuncu
""".split())

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_WORD = re.compile(r"[0-9]+|[^\W\d_]+", re.UNICODE)

MAX_FRAGMENT_WORDS = 5      # bunun üstü kısa sayılmaz


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split((text or "").strip()) if s.strip()]


def _is_grounded(sentence: str) -> bool:
    """Cümle somut bir dayanak taşıyor mu: özel ad, rakam ya da sayı sözcüğü."""
    words = _WORD.findall(sentence)
    for i, w in enumerate(words):
        if w.isdigit():
            return True
        fold = locale_fold(w)
        if fold in _NUM_WORDS:
            return True
        # Cümle başı dışında büyük harfle başlayan sözcük = özel ad
        if i > 0 and w[:1].isupper():
            return True
    return False


def dangling_fragments(text: str, *, max_words: int = MAX_FRAGMENT_WORDS) -> list[str]:
    """Kısa + soyut + dayanaksız cümleler ("Asıl mesele hız.").

    Boş liste = her cümle ya yeterince uzun ya da somut bir dayanağı var.
    Yanlış pozitif riski bilinçli olarak DÜŞÜK tutuldu: cümle hem kısa OLMALI,
    hem başlık kelimesi içermeli, hem de hiçbir özel ad/sayı taşımamalı.
    """
    out: list[str] = []
    for s in _sentences(text):
        words = _WORD.findall(s)
        if not words or len(words) > max_words:
            continue
        folds = {locale_fold(w) for w in words}
        if not (folds & _META_WORDS):
            continue
        if _is_grounded(s):
            continue
        out.append(s)
    return out


def fragment_feedback(fragments: list[str]) -> str:
    """LLM'e verilecek düzeltme talimatı (prompt'un sonuna eklenir)."""
    liste = " · ".join(f'"{f}"' for f in fragments)
    return (
        "\n\nSTYLE ERROR — dangling abstract sentences: " + liste + "\n"
        "Each of these announces an abstraction with nothing concrete in the same "
        "sentence, so the listener cannot tell what it refers to (there is no rewind in "
        "audio). Rewrite the narration so that every sentence stands on its own: merge "
        "each fragment into the sentence that carries its fact "
        "(e.g. 'Asıl mesele hız.' + 'Saldırgan bir ay önce partiye geçmişti.' → "
        "'Asıl mesele hız: saldırgan bir ay önce partiye geçmişti.'), or delete it. "
        "Keep the same shape, facts, length budget and language. Return ONLY the JSON."
    )
