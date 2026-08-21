"""Trend DİKEYLERİ — Google Trends kategori kimliklerinin okunabilir kümeleri.

Google her trendi kendisi sınıflandırıyor (``TrendingEntry.category_ids``).
Kanal YAML'ında ham kimlik listesi TUTULMAZ: okunmaz, ve harita değişirse her
kanal dosyası bozulur. Kanal bir DİKEY adı yazar, karşılığı burada durur.

Harita 2026-08-21'de ampirik çıkarıldı (2090 trend, altı bölge; kategori başına
en yüksek hacimli terimlerden). Google'ın alfabetik 19'luk listesiyle birebir
DEĞİL: 20 (Hava & Afet) o listede yok, 12 hiç görülmedi.
"""
from __future__ import annotations

CATEGORY_NAMES: dict[int, str] = {
    1: "Otomotiv",
    2: "Güzellik & Moda",
    3: "İş & Finans",
    4: "Eğlence",
    5: "Yeme-İçme",
    6: "Oyun",
    7: "Sağlık",
    8: "Hobi & Boş zaman",
    9: "İş & Eğitim",
    10: "Hukuk & Devlet",
    11: "Diğer / yerel olay",
    13: "Hayvan",
    14: "Siyaset",
    15: "Bilim",
    16: "Alışveriş",
    17: "Spor",
    18: "Teknoloji",
    19: "Seyahat",
    20: "Hava & Afet",
}

# Siyaset (14) BİLEREK hiçbir dikeyde yok: altı bölgede de günde 1-11 trend
# veriyor (eşik ~8) ve kutuplaştırıcı. Dikey olarak kurulamaz.
VERTICALS: dict[str, frozenset[int]] = {
    "spor": frozenset({17}),
    "para": frozenset({3, 16}),
    "magazin": frozenset({4, 2}),
    "adalet": frozenset({10}),
    "olay": frozenset({11, 20}),
    "teknoloji": frozenset({18, 15, 6}),
}

VERTICAL_LABELS: dict[str, str] = {
    "spor": "Spor — lig, maç, transfer, milli takım",
    "para": "Para — ekonomi, zam, faiz, şirket, alışveriş",
    "magazin": "Magazin — ünlü, dizi, film, moda",
    "adalet": "Adalet — dava, gözaltı, kurum, resmi karar",
    "olay": "Olay — yerel haber, kaza, deprem, hava",
    "teknoloji": "Teknoloji — teknoloji, bilim, oyun",
}


def categories_for(vertical: str | None) -> frozenset[int] | None:
    """Dikey adının kategori kümesi. None/boş → None (süzme yok).

    Bilinmeyen ad KeyError fırlatır: sessizce "süzme yok"a düşmek, ayarı açık
    sanılıp kapalı çalışan bir kanal demektir (bkz. saga sınırı vakası).
    """
    if not vertical:
        return None
    return VERTICALS[str(vertical).strip().lower()]


def matches(categories, vertical: str | None) -> bool:
    """Bu trend o dikeye giriyor mu?

    ÇOKLU kategoride HERHANGİ biri yeterlidir: gerçek veride 'sucuk' [3, 5]
    etiketli ve para dikeyinde kalmalı.

    Kategorisi olmayan trend (RSS yedeği) dikeyi olan kanala GİREMEZ — hangi
    dikeye ait olduğu bilinmiyor, tahmin etmek "her şey"e geri dönüştür.
    """
    want = categories_for(vertical)
    if want is None:
        return True
    return bool(want & set(categories or ()))
