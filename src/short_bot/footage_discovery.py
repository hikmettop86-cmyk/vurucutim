"""GERÇEK görüntü-önce: KONU STOKTAN DOĞAR (kullanıcı önerisi, 2026-07-16).

Eski akış konuyu ÖNCE seçip (konu bankası) o konuya stok arıyordu → havuz kıtsa
ya looplu video çıkıyordu (short 858: tek klip 15 alt-kesim döndü) ya üretim
düşüyordu (5. okçu koşusu: hiç klip kalmadı). Kullanıcının teşhisi doğruydu:
'pexels/pixabay'dan görüntüleri al, senaryoyu ONA GÖRE uydur'.

Bu modül akışı tersine çevirir:
  1. Jenerik AKSİYON sorgularından (seed-rotasyonlu) Pexels/Pixabay taranır
  2. Adayların thumbnail'ları vision'la tariflenir (ucuz, indirme yok)
  3. LLM tek çağrıyla EN AZ ``MIN_SUBJECT_CLIPS`` ayrık klibi olan bir ÖZNE seçer,
     son videolarla çakışmayanı, ve mizah açılı Türkçe KONUYU türetir
  4. Çağıran (reel._prepare_footage_driven) o klipleri indirir; senaryo zaten
     tariflerden yazılıyor (write_footage_driven_narration)

'Stokta olmayan konu' yapısal olarak imkânsızlaşır: özne, klipleri GÖRÜLDÜKTEN
sonra seçilir. Keşif çökerse None döner — çağıran eski konu-yoluna düşer.
"""
from __future__ import annotations

import hashlib
import logging

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Özne bu kadar AYRIK klip sunamıyorsa aday bile değil (858 dersi: az klip = loop).
# 4 → 6 (MARGIN, kök-neden analizi 2026-07-17): discover_subject özneyi THUMBNAIL'dan
# seçiyor (hareket GÖRÜLEMEZ); indirilen klipler motion gate'e (_fd_clip_ok) takılıyor —
# stok hayvan klipleri çoğu durgun (güneşlenen/oturan/zoo). Tam 4 seçince 2 durgun elenince
# <3 kalıp üretim düşüyordu (leopar/karakal). 6 seçmek 2-3 durgun-rediyle bile ≥3 hareketli
# klip + yedek havuz bırakır; ayrıca bol-footage'lı (=genelde dinamik) öznelere yöneltir.
MIN_SUBJECT_CLIPS = 6

# Jenerik aksiyon sorguları: tür adı YOK — havuz ne veriyorsa o. Mizah kanalının
# 'karakterli hayvan' ihtiyacına göre aksiyon/çatışma ağırlıklı.
DISCOVERY_QUERIES: list[str] = [
    "animals fighting",
    "animal hunting prey",
    "funny animal",
    "wildlife action",
    "predator chasing",
    "monkey mischief",
    "birds of prey hunting",
    "underwater predator",
    "reptile attack",
    "big cat hunting",
    "animals playing",
    "dangerous animal",
    "animal standoff",
    "wild animal running",
    "octopus squid ocean",
    "insect macro action",
]


class DiscoveredSubject(BaseModel):
    """LLM'in stok taramasından seçtiği özne + türettiği konu."""
    subject_en: str = Field(min_length=3, max_length=60)   # footage sorgusu olur
    topic_tr: str = Field(min_length=10, max_length=200)   # mizah açılı konu cümlesi
    clip_indices: list[int] = Field(min_length=MIN_SUBJECT_CLIPS)


def _pick_queries(seed: int, n: int = 3) -> list[str]:
    """Seed-rotasyonlu, birbirinden FARKLI n keşif sorgusu (tuzlanmış hash)."""
    out: list[str] = []
    pool = list(DISCOVERY_QUERIES)
    for k in range(n):
        h = hashlib.sha1(f"{seed}:disc{k}".encode("utf-8")).hexdigest()
        out.append(pool.pop(int(h, 16) % len(pool)))
    return out


def discover_subject(*, sources, vision_call, invoke, seed: int = 0,
                     recent_titles: list[str] | None = None,
                     avoid_subjects: list[str] | None = None,
                     per_query: int = 15, max_describe: int = 30):
    """Stoku tara, özne seç, konu türet.

    Döner: ``(DiscoveredSubject, [FootageCandidate, ...])`` — adaylar seçilen
    klip sırasında. Keşif kurulamazsa (kaynak yok / vision yok / LLM çöktü /
    yeterli klipli özne yok) ``None`` — çağıran eski konu-yoluna düşer.

    ``invoke``: (prompt, schema) -> instance (test enjeksiyonu / gerçek LLM).
    """
    from short_bot.footage_matcher import describe_footage
    if not sources or vision_call is None:
        return None

    # 1) Tara — sorgu × kaynak; ident/url ile tekilleştir.
    queries = _pick_queries(seed)
    cands: list = []
    seen_ids: set[str] = set()
    for q in queries:
        for src in sources:
            try:
                bulunan = src.search(q, max_results=per_query, orientation="portrait")
            except Exception as e:  # noqa: BLE001 — tek kaynak taramayı düşürmesin
                log.info(f"  keşif: {getattr(src, 'name', '?')} '{q}' arama hatası: {e}")
                continue
            for c in bulunan:
                key = c.ident or c.url
                if key in seen_ids or not c.image:
                    continue          # thumbnail'sız aday tariflenemez → alma
                seen_ids.add(key)
                cands.append(c)
    if len(cands) < MIN_SUBJECT_CLIPS:
        log.info(f"  keşif: yalnız {len(cands)} aday bulundu → keşif atlanıyor")
        return None
    log.info(f"  keşif: {len(queries)} sorgu ({', '.join(queries)}) → {len(cands)} aday")

    # 2) Thumbnail tarifleri (paralel; üst sınırla — vision maliyeti bütçeli).
    cands = cands[:max_describe]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        descs = list(ex.map(
            lambda c: describe_footage(c.image, vision_call=vision_call), cands))
    tarifli = [(i, d) for i, d in enumerate(descs) if (d or "").strip()]
    if len(tarifli) < MIN_SUBJECT_CLIPS:
        log.info(f"  keşif: yalnız {len(tarifli)} aday tariflendi → keşif atlanıyor")
        return None

    # 3) LLM: özne seç + mizah konusu türet (tek çağrı).
    listing = "\n".join(f"{i}: {d}" for i, d in tarifli)
    son = "\n".join(f"- {t}" for t in (recent_titles or [])[:15]) or "- (yok)"
    prompt = (
        "Aşağıda stok video kütüphanesinden toplanmış kliplerin görsel tarifleri var "
        f"(index: tarif):\n{listing}\n\n"
        "GÖREV: Bu havuzdan, mizahi bir hayvan videosu için EN İYİ ÖZNEYİ seç.\n"
        "KURALLAR:\n"
        f"  • Seçtiğin öznenin havuzda EN AZ {MIN_SUBJECT_CLIPS} FARKLI klibi olmalı "
        "(aynı TÜR, farklı çekimler). clip_indices'e o kliplerin index'lerini yaz — "
        "EN İYİ (net, aksiyonlu, özne belirgin) klipleri seç.\n"
        "  • Özne bir HAYVAN olmalı ve KARAKTERLİ olmalı (kavga, av, kovalamaca, "
        "kurnazlık, gösteriş) — mizaha elverişli. İnsan/manzara/nesne ÖZNE OLAMAZ.\n"
        "  • SON VİDEOLARLA ÇAKIŞMA: aşağıdaki son video konularıyla AYNI ya da çok "
        f"benzer özneyi SEÇME (tekrar hissi verir):\n{son}\n"
        + (("  • ŞU ÖZNELERİ DE SEÇME (bu koşuda klipleri hareket kapısından "
            "geçemedi): " + ", ".join(avoid_subjects) + "\n")
           if avoid_subjects else "")
        + "  • subject_en: öznenin İngilizce kısa adı (stok arama sorgusu olarak da "
        "kullanılacak — 'archerfish', 'mantis shrimp' gibi).\n"
        "  • topic_tr: kliplerde GERÇEKTEN GÖRÜNEN davranıştan türetilmiş, mizah açılı "
        "TEK cümlelik Türkçe konu ('Bizimki ... yapıyor' tadında). Kliplerde OLMAYAN "
        "bir olay uydurma — senaryo bu kliplere yazılacak.\n"
        'SADECE JSON: {"subject_en": "...", "topic_tr": "...", "clip_indices": [..]}'
    )
    try:
        v = invoke(prompt, DiscoveredSubject)
    except Exception as e:  # noqa: BLE001 — keşif üretimi durdurmaz, yola düşülür
        log.warning(f"  keşif: özne seçimi çöktü ({e}) → eski konu-yoluna düşülüyor")
        return None

    gecerli = [i for i in dict.fromkeys(v.clip_indices) if 0 <= i < len(cands)]
    if len(gecerli) < MIN_SUBJECT_CLIPS:
        log.info(f"  keşif: seçilen özne '{v.subject_en}' yalnız {len(gecerli)} geçerli "
                 f"klip gösterdi → keşif atlanıyor")
        return None
    secilen = [cands[i] for i in gecerli]
    log.info(f"  keşif: özne='{v.subject_en}' ({len(secilen)} klip) → konu: {v.topic_tr}")
    return v, secilen
