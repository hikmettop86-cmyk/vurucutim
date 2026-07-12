"""Anlatımdaki sayıları yakala → overlay'de büyük, animasyonlu vurgu.

Sayılar dikkat çeker ve paylaşılır ("240 parça", "24 milyon", "%90"). Karaoke
kelimelerinde RAKAM içerenler yakalanır; hemen ardından gelen birim/çarpan
kelimesi vurguya katılır. Yazıyla sayılar ("bir", "iki") YAKALANMAZ — yanlış
pozitif üretirler.
"""
from __future__ import annotations

import re

MAX_POPS = 4   # video başına en fazla vurgu (fazlası gürültü)

# Rakam içeren kelime: 240, %90, 1.000, 3,5, 24
_NUM_RE = re.compile(r"^[%€$]?\d[\d.,]*[%]?$")

# Sayının hemen ardından gelirse vurguya KATILAN kelimeler.
_UNITS = {
    "milyon", "milyar", "bin", "trilyon",
    "ton", "kilo", "kilogram", "gram", "metre", "kilometre", "santim",
    "saniye", "dakika", "saat", "gün", "hafta", "ay", "yıl", "yüzyıl",
    "kat", "parça", "parçaya", "derece", "litre", "kişi", "adet",
}


def _numeric_value(token: str) -> float:
    """Sıralama için kaba büyüklük (binlik ayraç/ondalık toleranslı)."""
    t = re.sub(r"[^\d.,]", "", token or "")
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t or 0)
    except ValueError:
        return 0.0


def find_numbers(words) -> list[dict]:
    """TimedWord listesinde sayı vurgularını bul.

    Dönüş (zaman sırasında): [{"text", "start_s", "end_s", "word_index"}].
    En fazla MAX_POPS; fazlaysa EN BÜYÜK değerliler tutulur.
    """
    hits: list[dict] = []
    ws = list(words or [])
    i = 0
    while i < len(ws):
        tok = (ws[i].word or "").strip().strip(".,;:!?")
        if not _NUM_RE.match(tok):
            i += 1
            continue
        # Sayının KENDİ kelimesinin zamanını sakla — birim birleşince i ilerler,
        # start_s bir sonraki kelimeye kaymamalı.
        start = ws[i].start_s
        wi = i
        text = tok
        end = ws[i].end_s
        if i + 1 < len(ws):
            nxt = (ws[i + 1].word or "").strip().strip(".,;:!?").lower()
            if nxt in _UNITS:
                text = f"{tok} {nxt}"
                end = ws[i + 1].end_s
                i += 1
        hits.append({"text": text, "start_s": start, "end_s": end,
                     "word_index": wi, "_val": _numeric_value(tok)})
        i += 1
    if len(hits) > MAX_POPS:
        hits = sorted(hits, key=lambda h: -h["_val"])[:MAX_POPS]
    hits.sort(key=lambda h: h["start_s"])
    for h in hits:
        h.pop("_val", None)
    return hits
