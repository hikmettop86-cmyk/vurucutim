"""Kalıp tekrarını kıran ifade havuzu + aşınmış kalıp denetçisi.

NEDEN VAR: prompt, mikro-döngü bağlaçlarını BİREBİR CÜMLE olarak veriyordu
("Ama asıl garip olan şu:" / "Ve burada iş çığırından çıkıyor." ...) ve LLM onları
olduğu gibi kopyalıyordu. Ölçüldü: kayda geçen üç anlatımın İKİSİNDE aynı iki cümle
kelimesi kelimesine geçiyor. İki videomuzu üst üste izleyen biri bunu anında fark
eder — tam da kırmaya çalıştığımız otomasyon parmak izi.

İKİ KATMANLI ÇÖZÜM:
  1. ÜRETİM: prompt artık cümle değil YÖNERGE veriyor (bkz. reel_subscribe'daki
     COMMENT_STYLES deseni) ve yönergeler seed'e göre dönüyor — her video farklı
     bir alt küme görüyor.
  2. DENETİM: üretilen anlatım aşınmış kalıplara karşı taranır; bulunursa LLM'e
     ne yaptığı söylenip yeniden yazdırılır. Prompt'a "kullanma" demek yetmiyor —
     ölçüldüğü gibi model yine kullanıyor.

Yönergeler ve kalıplar artık DİL PAKETİNDEN geliyor (lang_pack). Türkçe sabit
oldukları sürece Almanca kanalda denetçi HİÇBİR ŞEY yakalayamıyordu — ve bu sessizdi:
hata yok, log yok, sadece koruma yok.
"""
from __future__ import annotations

import hashlib
import re

from short_bot.text_normalize import locale_fold


def _norm(text: str, lang: str) -> str:
    """Dile duyarlı küçültme + noktalama temizliği (kalıp eşleşmesi için).

    Dil ŞART: locale_fold Türkçe için 'I' → 'ı' yapıyor. Almanca metinde bu 'Ich'i
    'ıch' yapar ve r'\\bich\\b' asla eşleşmez — denetçi çalışıyor görünüp sıfır şey
    bulur. (Kalıplar bu yüzden noktalamasız yazılmalı: "what's up" → "what s up".)
    """
    return re.sub(r"[^\w\s]", " ", locale_fold(text, lang)).replace("  ", " ")


def pick_styles(seed: int, n: int = 4, *, pack) -> list[str]:
    """Bu videonun göreceği bağlaç YÖNERGELERİ. Deterministik: aynı seed → aynı set.

    Havuzun tamamını her videoya vermek işe yaramaz — LLM ilk örneklere yapışıyor.
    Alt küme döndürmek, videodan videoya farklı bir tonu zorunlu kılar.
    """
    havuz = pack.connective_styles
    n = max(1, min(n, len(havuz)))
    idx = list(range(len(havuz)))
    # Deterministik karıştırma (Fisher-Yates, hash-güdümlü).
    for i in range(len(idx) - 1, 0, -1):
        h = int(hashlib.sha1(f"{seed}:conn:{i}".encode()).hexdigest(), 16)
        j = h % (i + 1)
        idx[i], idx[j] = idx[j], idx[i]
    return [havuz[i] for i in idx[:n]]


def find_overused(text: str, *, pack) -> list[str]:
    """Metindeki aşınmış kalıplar: hem BİREBİR ifadeler hem ÖRÜNTÜLER.

    Örüntü katmanı şart: dizge denetimi "bunu biliyor muydunuz"u yakalıyor ama
    "...sahip olduğunu biliyor muydunuz?"u KAÇIRIYOR (gerçek kaçak, bölüm #2) —
    oysa yasak olan şey dizge değil, kalıbın kendisi.

    Dönen liste LLM'e geri bildirimde gösterilir, o yüzden ETİKETLER hedef dilde.
    """
    t = _norm(text, pack.lang)
    bulunan = [p for p in pack.overused if _norm(p, pack.lang) in t]
    bulunan += [op.label for op in pack.overused_patterns
                if re.search(op.pattern, t, re.IGNORECASE)]
    return bulunan
