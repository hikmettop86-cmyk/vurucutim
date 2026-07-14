"""Konu ÖNERİSİ: damıtma ve üretim tek prompt, arkasında doğrulama kapısı.

NEDEN BİRLEŞTİ (hepsi ölçüldü):

  • Kanıt (outlier videosu) KAYNAK VİDEOYA aittir, konu CÜMLESİNE değil. 871 kat
    patlamış bir videodan damıtılan cümle içi boş çıkabiliyor:
        "Gerçek bir sinir sistemi, ... karmaşık bir otoyol"        ← hiçbir şey demiyor
        "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır" ← prompt'un YASAK örneği

  • Sonnet 5, hiçbir YouTube verisi görmeden daha iyi konu yazıyor:
        "Mide iç zarı hücrelerini her 3-4 günde bir tamamen yeniler"
        "Bir hücrenin DNA'sı her gün ~10 bin kez hasar görür"

  • Damıtma sistemin EN UCUZ modelinde koşuyordu (gemini-3.1-flash-lite) ve bankanın
    %85'i çöp oldu (27 aktif konudan 23'ü); bazıları BİLİMSEL OLARAK YANLIŞ.

O yüzden kanıt bir ZORUNLULUK değil, İLHAM. Kanıt yoksa saf üretim koşar:
BANKA ASLA KURUMAZ, referans kanal ve YouTube API anahtarı OPSİYONELDİR.

MEKANİK FALLBACK YOK: eskiden LLM yokken ham başlık aynen konu oluyordu. Ölçülen çöpün
kaynaklarından biri o. Konu üretemiyorsak sessizce çöp üretmektense DURURUZ.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

log = logging.getLogger(__name__)

_LANG_NAMES = {"tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
               "es": "İspanyolca", "fr": "Fransızca"}

# Çıktıda video-TARİFİ kalıpları (konu değil meta-açıklama) — yasak.
# Gerçek üretim hatası (2026-07-12): "…tanıtan bir seri", "…ele alan bir skeç".
# Gerçek kaçak: "anatomisi 3 boyutlu CANLANDIRMALARLA gösterilir" — bu bir İDDİA değil,
# kaynak videonun NASIL YAPILDIĞININ tarifi. Konu bankası iddia tutar, yapım notu değil.
_META_WORDS = ("video", "belgesel", "seri", "skeç", "inceleme", "anlatım",
               "sunum", "içerik", "tanıtan", "anlatan", "özetleyen",
               "ele alan", "konu alan", "keşfeden bir", "yolculuğu",
               "canlandırma", "animasyon", "3 boyutlu", "3d ", "görselleştir",
               "gösterilir", "gösteren")


class ProposedTopic(BaseModel):
    topic: str
    source_title: str = ""      # kanıt kullanıldıysa
    views: int = 0
    subs: int = 0
    hook_pattern: str = ""
    source: str = "llm"         # "reference" | "search" | "llm"


class _Proposed(BaseModel):
    topics: list[ProposedTopic]


def _evidence_block(evidence: list[dict]) -> str:
    if not evidence:
        return ""
    satirlar = "\n".join(
        f'- "{e["source_title"]}"  ({e.get("views", 0):,} izlenme / '
        f'{e.get("subs", 0):,} abone)'
        for e in evidence if (e.get("source_title") or "").strip())
    if not satirlar:
        return ""
    return f"""
KANIT — bu nişte KÜÇÜK kanallarda PATLAMIŞ (outlier) shorts başlıkları:

{satirlar}

Bunlar izleyicinin neye tepki verdiğini gösterir.
İLHAM AL — ama KOPYALAMAK ZORUNDA DEĞİLSİN.
Bir başlıktan somut bir olgu ÇIKARAMIYORSAN onu ATLA ve kendi bildiğin daha iyi bir
olguyu yaz.

(ÖLÇÜLDÜ: başlığı zorla damıtmak içi boş cümle üretiyor — "Gerçek bir sinir sistemi,
karmaşık bir otoyol" gibi. Videonun 871 kat patlamış olması, ondan çıkardığın cümlenin
iyi olduğunu göstermez. Boş bir cümle, boş bir video demektir.)

Bir konuyu bir başlıktan çıkardıysan `source_title`, `views`, `subs` alanlarını
KAYNAKTAN AYNEN kopyala. Kendi bildiğin bir olguyu yazdıysan bu üç alanı BOŞ/0 bırak.
"""


def _prompt(niche: str, lang: str, evidence: list[dict], existing: list[str],
            count: int) -> str:
    mevcut = "\n".join(f"- {t}" for t in existing if (t or "").strip())
    mevcut_blok = (f"\nBUNLAR ZATEN BANKADA — TEKRAR ETME, benzerini de yazma:\n"
                   f"{mevcut}\n" if mevcut else "")
    return f"""Bir YouTube Shorts kanalı için {count} KONU üret.

NİŞ: {niche}
HEDEF FORMAT: 40 saniyelik faceless "ilginç bilgi" shorts — stok görüntü +
seslendirme. İzleyici 40 saniyede "vay be, bunu bilmiyordum" demeli.
DİL: {lang}
{_evidence_block(evidence)}{mevcut_blok}
KURALLAR (ÇOK ÖNEMLİ — hepsi GERÇEK HATALARDAN öğrenildi):

- Konu bir İDDİA ya da ŞAŞIRTICI GERÇEK cümlesidir; videoyu TARİF ETMEZ.
    ✗ "Einstein'ın beynini konu alan bir inceleme"
    ✓ "Einstein'ın beyni ölümünden sonra izinsiz çalındı ve 40 yıl kavanozda gezdirildi"

- GERÇEĞİ İÇER, VAAT ETME (en sık kaçan hata): konu şaşırtıcı olguyu KENDİSİ
  SÖYLEMELİ; "şaşırtıcıdır", "inanılmazdır", "rakamlarla ifade edilebilir" gibi
  ifadelerle onu ERTELEMEMELİ.
    ✗ "Vücuttaki kemik sayısı şaşırtıcı rakamlarla ifade edilebilir"   ← VAAT
    ✓ "Bebekler 300 kemikle doğar; yetişkinlikte bu sayı 206'ya iner"  ← GERÇEK

- İÇİ BOŞ GENELLEME YASAK: konu SPESİFİK ve ŞAŞIRTICI olmalı.
    ✗ "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır"  ← hiçbir şey demiyor
    ✓ "Karaciğerinin %70'ini kaybetsen bile 3 haftada kendini yeniden büyütür"
  Test: izleyici bunu ZATEN biliyor mu? Biliyorsa YAZMA.

- SÖZDE-BİLİM YASAK (SERT ELEME): konu BİLİMSEL OLARAK DOĞRULANABİLİR olmalı.
    ✗ alternatif tıp / mucize şifa / detoks / mistik şifa / enerji-aura-çakra
    ✗ kanıtsız sağlık tavsiyesi, komplo teorileri
  GERÇEK HATA: bir BİLİM kanalına "Mekke'nin adem elması, mistik bir şifa kaynağı"
  konusu girdi. Kanalın otoritesi ÜRÜNÜDÜR; bir tek sözde-bilim videosu onu yakar.
  Test: bunu bir ders kitabında bulabilir misin? Hayırsa YAZMA.

- BİLİMSEL OLARAK DOĞRU OLMALI. GERÇEK HATA (bankaya girdi): "Vücudunuz muzu
  sindirim sistemi boyunca saniyeler içinde sindirir" — sindirim SAATLER sürer.
  Yanlış bir olgu kanalın güvenilirliğini bitirir. Emin değilsen YAZMA.

- FORMAT UYUMU: tek, doğrulanabilir, şaşırtıcı GERÇEK. Şunları ATLA: film/dizi
  özetleri, kurgu sahneler, aşk/dram hikâyeleri, kişi-odaklı anlatılar, vlog/meme,
  hikâye anlatımı gerektiren konular.

- HEDEF KİTLE: {lang} konuşan GENEL izleyici. Evrensel merak (uzay, insan vücudu,
  tarihin şok anları, gizemler) İYİ; fazla akademik/teknik konular, başka ülkeye
  özgü yerel içerik, tanınmayan kişiler → YAZMA.

- ELEMEKTEN ÇEKİNME: {count} konu istiyoruz ama zorlama konu üretme. Az ve sağlam,
  çok ve boştan iyidir.

SADECE JSON: {{"topics": [{{"topic": "<{lang} tek çarpıcı iddia cümlesi>",
  "source_title": "<kanıttan geldiyse orijinal başlık, yoksa boş>",
  "views": <int, kanıt yoksa 0>, "subs": <int, kanıt yoksa 0>,
  "hook_pattern": "<{lang} 2-4 kelime örüntü, ör. 'sayı + beklenmedik iddia'>"}}]}}"""


def _is_meta(topic: str) -> bool:
    low = (topic or "").lower()
    return any(w in low for w in _META_WORDS)


def propose_topics(niche: str, *, language: str, evidence: list[dict],
                   existing: list[str], count: int, llm) -> list[ProposedTopic]:
    """Nişten konu öner. ``evidence`` boşsa saf üretim (banka asla kurumaz).

    ``llm``: (prompt, schema) → schema örneği döndüren çağrılabilir. None ise
    RuntimeError — MEKANİK FALLBACK YOK (bkz. modül docstring'i).
    """
    if llm is None:
        raise RuntimeError(
            "konu üretilemedi: LLM yok. (Mekanik fallback kaldırıldı — ham başlığı "
            "konu diye bankaya koymak, ölçülen çöpün kaynaklarından biriydi.)")

    lang = _LANG_NAMES.get(language, "Türkçe")
    # Referans kanal outlier'ları 'reference', arama outlier'ları 'search'.
    ref_titles = {(e.get("source_title") or "").strip().lower()
                  for e in evidence if e.get("ref")}

    v = llm(_prompt(niche, lang, evidence, existing, count), _Proposed)

    out: list[ProposedTopic] = []
    for t in v.topics:
        konu = (t.topic or "").strip()
        if not konu or _is_meta(konu):
            continue
        src = (t.source_title or "").strip()
        if not src:
            # Kanıtsız — modelin kendi bildiği olgu. Sahte izlenme/abone taşımasın.
            t.source = "llm"
            t.views = t.subs = 0
        elif src.lower() in ref_titles:
            t.source = "reference"
        else:
            t.source = "search"
        t.topic = konu
        out.append(t)
        if len(out) >= count:
            break

    log.info(f"[konu] {len(v.topics)} öneri → {len(out)} geçerli "
             f"(kanıt: {len(evidence)} başlık)")
    return out


# --- DOĞRULAMA KAPISI ------------------------------------------------------

class Verdict(BaseModel):
    index: int
    solid: bool
    reason: str = ""


class _Verdicts(BaseModel):
    verdicts: list[Verdict]


_VERIFY_PROMPT = """Aşağıda bir YouTube Shorts kanalının konu adayları var. Her birini
ŞU KURALLARA göre yargıla:

1. GERÇEĞİ İÇERİR, VAAT ETMEZ. Konu şaşırtıcı olguyu KENDİSİ söylemeli.
     SAĞLAM: "Bebekler 300 kemikle doğar; yetişkinlikte bu sayı 206'ya iner"
     ÇÖP:    "Vücuttaki kemik sayısı şaşırtıcı rakamlarla ifade edilebilir"  ← VAAT

2. İÇİ BOŞ GENELLEME DEĞİL. Spesifik, doğrulanabilir, izleyicinin BİLMEDİĞİ bir olgu.
     ÇÖP: "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır" ← hiçbir şey demiyor
     ÇÖP: "İnsan vücudu şaşırtıcı bir sistemdir"                     ← boş

3. BİLİMSEL OLARAK DOĞRU. GERÇEK ÖRNEK (bankaya girmişti): "Vücudunuz muzu sindirim
   sistemi boyunca saniyeler içinde sindirir" — sindirim SAATLER sürer. ÇÖP.

Bir konu 40 saniyelik bir shorts'un TEK OMURGASI olacak. İçinde somut bir sayı,
mekanizma ya da şaşırtıcı olgu YOKSA o video da boş çıkar.

solid=true YALNIZ üçünü de geçiyorsa. Şüphedeysen solid=false.

{liste}

SADECE JSON: {{"verdicts": [{{"index": <int>, "solid": <bool>,
  "reason": "<kısa gerekçe>"}}]}}"""


def verify_topics(topics: list[str], *, language: str, llm) -> list[Verdict]:
    """Her konuyu kurallara göre yargıla. Konularla AYNI uzunlukta, AYNI sırada liste.

    NEDEN VAR (ölçüldü): üretim prompt'u "Vücudumuzdaki her organ kusursuz bir uyum
    içinde çalışır" cümlesini YASAK ÖRNEK olarak birebir veriyordu — ve model onu
    kelimesi kelimesine yazıp bankaya soktu. Prompt'a güvenmek YETMİYOR; ikinci bir
    göz şart.

    Denetim ÇÖKERSE üretimi durdurmayız: hepsi sağlam sayılır ve LOGLANIR. Aksi hâlde
    tek bir LLM arızası bankayı sıfırlardı.
    """
    if not topics:
        return []
    if llm is None:
        return [Verdict(index=i, solid=True, reason="denetlenemedi (LLM yok)")
                for i in range(len(topics))]

    liste = "\n".join(f"{i}. {t}" for i, t in enumerate(topics))
    try:
        v = llm(_VERIFY_PROMPT.format(liste=liste), _Verdicts)
    except Exception as e:   # noqa: BLE001 — denetim çökse de üretim durmamalı
        log.warning(f"[konu] doğrulama kapısı çalışmadı ({e}) → hepsi geçti sayılıyor")
        return [Verdict(index=i, solid=True, reason=f"denetlenemedi ({e})")
                for i in range(len(topics))]

    # Model bazı konulara yargı vermemiş olabilir. Yargısı OLMAYANI SAĞLAM SAYMAK
    # kapıyı delmektir — çöp konu sessizce içeri girer.
    yargi = {int(x.index): x for x in v.verdicts}
    return [yargi.get(i, Verdict(index=i, solid=False,
                                 reason="model bu konuya yargı vermedi"))
            for i in range(len(topics))]
