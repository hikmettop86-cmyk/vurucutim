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
"""
from __future__ import annotations

import hashlib
import re

from short_bot.tts.fidelity import _fold

# Mikro-döngü bağlaçları: her beat bir sonrakine BORÇ bırakarak bitmeli. Ama NASIL
# yazılacağı LLM'e ait — biz İŞLEVİ tarif ediyoruz, cümleyi değil.
CONNECTIVE_STYLES = (
    "BEKLENTİYİ KIR: izleyicinin şu an aklından geçen açıklamanın YANLIŞ olduğunu "
    "ima et, doğrusunu daha söyleme.",
    "ÖLÇEĞİ BÜYÜT: az önce verdiğin sayının/olgunun aslında küçük kaldığını, asıl "
    "büyüğün geldiğini sezdir.",
    "GİZLİ AKTÖR: olayın ARKASINDA henüz adını anmadığın bir sebep olduğunu duyur.",
    "GERİ SAYIM: bir eşiğe/ana yaklaşıldığını söyle — 've sonra' demeden kes.",
    "ÇELİŞKİ AÇ: az önce söylediğinle çelişen bir gerçek olduğunu haber ver.",
    "MALİYETİ İMA ET: bu yeteneğin/olgunun bir bedeli olduğunu söyle, bedeli sakla.",
    "KİŞİSELLEŞTİR: bunun izleyicinin kendi bedeninde/hayatında da olduğunu ima et.",
    "SON ANDA ÇEVİR: 'ama' ile başlayıp az önceki resmi tersine çeviren bir cümle kur.",
)

# ÖLÇÜLEN aşınmış kalıplar: prompt bunları örnek verdiği için LLM birebir kopyaladı.
# Buraya giren bir ifade artık ÜRETİMDE REDDEDİLİR.
OVERUSED = (
    "ama asıl garip olan şu",
    "ve burada iş çığırından çıkıyor",
    "sebebi ise sandığın şey değil",
    "bir de bunu duymadın",
    "bir de şunu duyun",
    "peki tüm bu",
    "inanılmaz ama gerçek",
)

# KALIP denetimi — DİZGE denetimi yetmiyor.
#
# GERÇEK KAÇAK (bölüm #2): yasak listesinde "bunu biliyor muydunuz" vardı, LLM
# "...sahip olduğunu biliyor muydunuz?" yazdı ve DENETİMDEN GEÇTİ. Yasak olan şey
# bir dizge değil, bir KALIP: cevaplanabilir bir evet/hayır sorusu hook DEĞİLDİR —
# izleyici onu 200 milisaniyede içinden cevaplar, gerilim çöker, kaydırır.
#
# (etiket, örüntü) — etiket LLM'e geri bildirimde gösterilir, örüntü metinde aranır.
OVERUSED_PATTERNS = (
    ("… biliyor muydunuz? (cevaplanabilir evet/hayır sorusu — hook değil)",
     r"\bbiliyor mu(ydunuz|ydun|sun|sunuz)\b"),
    ("… duymuş muydunuz? (aynı kalıp)",
     r"\bduymu[sş] mu(ydunuz|ydun)\b"),
    ("Merhaba arkadaşlar / dostlar (kanal açılışı — ilk saniyeyi harcar)",
     r"\bmerhaba\s+(arkada[sş]lar|dostlar|herkese)\b"),
    ("Bugün sizlere … anlatacağım (vaat değil, gündem duyurusu)",
     r"\bbug[uü]n\s+siz(lere|e)\b"),
    ("Hazır mısınız? (içi boş kalıp)",
     r"\bhaz[ıi]r m[ıi](s[ıi]n|s[ıi]n[ıi]z)\b"),
)


def _norm(text: str) -> str:
    """Türkçe-güvenli küçültme + noktalama temizliği (kalıp eşleşmesi için)."""
    return re.sub(r"[^\w\s]", " ", _fold(text)).replace("  ", " ")


def pick_styles(seed: int, n: int = 4) -> list[str]:
    """Bu videonun göreceği bağlaç YÖNERGELERİ. Deterministik: aynı seed → aynı set.

    Havuzun tamamını her videoya vermek işe yaramaz — LLM ilk örneklere yapışıyor.
    Alt küme döndürmek, videodan videoya farklı bir tonu zorunlu kılar.
    """
    n = max(1, min(n, len(CONNECTIVE_STYLES)))
    idx = list(range(len(CONNECTIVE_STYLES)))
    # Deterministik karıştırma (Fisher-Yates, hash-güdümlü).
    for i in range(len(idx) - 1, 0, -1):
        h = int(hashlib.sha1(f"{seed}:conn:{i}".encode()).hexdigest(), 16)
        j = h % (i + 1)
        idx[i], idx[j] = idx[j], idx[i]
    return [CONNECTIVE_STYLES[i] for i in idx[:n]]


def find_overused(text: str) -> list[str]:
    """Metindeki aşınmış kalıplar: hem BİREBİR ifadeler hem ÖRÜNTÜLER.

    Örüntü katmanı şart: dizge denetimi "bunu biliyor muydunuz"u yakalıyor ama
    "...sahip olduğunu biliyor muydunuz?"u KAÇIRIYOR (gerçek kaçak, bölüm #2) —
    oysa yasak olan şey dizge değil, kalıbın kendisi.
    """
    t = _norm(text)
    bulunan = [p for p in OVERUSED if _norm(p) in t]
    bulunan += [etiket for etiket, oru in OVERUSED_PATTERNS
                if re.search(oru, t, re.IGNORECASE)]
    return bulunan
