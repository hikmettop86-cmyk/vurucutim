"""Konu etiketlerini tek biçime indirir.

`Script.category` serbest metindir ve LLM her koşuda farklı yazıyor. Gerçek
dağılım (galatasaray, 695 short):

    Transfer 210 | transfer 138 | futbol 113 | spor 51 | Futbol 41 | Spor 32
    Futbol Transfer 14 | Transfer Haberleri 10 | Galatasaray 8 | ...

Aynı konu 4-5 kovaya bölününce learning/aggregator'ın kategori ortalamaları
n=2 eşiğinin altında kalıyor ve scorer'a giden ipucu boşalıyor. Buradaki
normalizasyon yalnız YAZIM farklarını katlar (büyük/küçük harf, boşluk) —
anlam birleştirmesi (ör. "Futbol Transfer" → "transfer-gelen") yapmaz, çünkü
geçmiş etiketler o ayrımı taşıyacak kadar ayrıntılı değil. İleriye dönük
ayrım kanal config'indeki canonical liste ile sağlanır.
"""
from __future__ import annotations

_PLACEHOLDER = "?"


def normalize_category(raw: str | None) -> str:
    """Kategori etiketini karşılaştırılabilir tek biçime indir.

    Boş/None girdi `"?"` döner (aggregator'ın mevcut bilinmeyen göstergesi).
    """
    if not isinstance(raw, str):
        return _PLACEHOLDER
    # "İ".lower() Python'da "i" + U+0307 (combining dot above) üretir; bu
    # görünmez karakter "İLGİNÇ" ile "ilginç" etiketlerini ayrı kovalara
    # düşürür. Türkçe'ye özgü tek harf olduğu için önce onu eşliyoruz.
    # NOT: "I" → "ı" dönüşümü YAPILMAZ — kanallar çok dilli (es/ja/de) ve
    # Türkçe kuralı İspanyolca "INFORMACIÓN"u "ınformacıón" yapardı.
    text = raw.replace("İ", "i").lower()
    collapsed = " ".join(text.split())
    return collapsed or _PLACEHOLDER
