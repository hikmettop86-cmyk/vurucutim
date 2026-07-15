"""Kanıt madencisi + konu bankası doldurma.

Madenci artık YALNIZ KANIT toplar (nişte patlamış outlier shorts başlıkları). Konuyu
YAZAN yer ``topic_propose`` — ve orası kanıtı bir ZORUNLULUK değil, İLHAM olarak
kullanır.

NEDEN AYRILDI (ölçüldü): kanıt KAYNAK VİDEOYA aittir, konu CÜMLESİNE değil. 871 kat
patlamış bir videodan zorla damıtılan cümle içi boş çıkabiliyor. Damıtma sistemin en
ucuz modelinde koşuyordu ve bankanın %85'i çöp oldu.

AKIŞ:
    kanıt   = mine_evidence(...)        ← YouTube Data API (OPSİYONEL)
    konular = propose_topics(...)       ← Sonnet 5; kanıt yoksa saf üretim
    yargı   = verify_topics(...)        ← DOĞRULAMA KAPISI
    taze    = fuzzy-dedup
    insert

API ANAHTARI VE REFERANS KANAL İKİSİ DE OPSİYONELDİR. İkisi de varsa konu daha
kanıtlı olur; yoksa üretim DURMAZ.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel
from rapidfuzz import fuzz

from short_bot.claude_cli import run_json

log = logging.getLogger(__name__)

_DUP_THRESHOLD = 80   # aynı kanaldaki mevcut konuya fuzzy oran eşiği

# Yalnız arama SORGUSU prompt'u kullanıyor (konu dili topic_propose'un işi).
_LANG_NAMES_Q = {"tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
                 "es": "İspanyolca", "fr": "Fransızca"}


def _short_query(niche_query: str, max_len: int = 90) -> str:
    """Uzun/talimatlı kanal konusunu kısa niş sorgusuna indir.

    generator.topic tam bir yönerge olabilir ("...gerilim kurarak anlat") — aramaya
    talimat değil NİŞ lazım; ilk cümle/iki-nokta öncesi + uzunluk katı.
    """
    q = (niche_query or "").strip()
    for sep in ("—", ":", ".", "\n"):
        head = q.split(sep)[0].strip()
        if len(head) >= 20:
            q = head
    return q[:max_len]


class _SearchQueries(BaseModel):
    queries: list[str]


# Kaç sorgu ÜRETİLİR (havuz çeşitliliği) ve kaçı ARANIR (kota).
# Aynı 3 sorgu her yenilemede aynı videoları getiriyordu; 6 sorgudan 3'ünü DÖNÜŞÜMLÜ
# kullanmak nişin farklı köşelerini tarar.
_QUERY_POOL = 6
_QUERY_USE = 3

# Kanıt sayısı: öneri sayısının katı. Damıtma değil ÖNERİ ürettiğimiz için model
# uymayan başlıkları atlayabiliyor — bol kanıt vermek ona seçenek bırakır.
_EVIDENCE_OVERSAMPLE = 3


def _search_queries(niche_query: str, language: str, llm_call,
                    keywords=None, rotate: int = 0) -> list[str]:
    """Nişten KISA YouTube arama sorguları üret.

    Uzun/talimatlı niş cümlesi YouTube aramasında 0 sonuç veriyor (gerçek ölçüm:
    'Bilim ve keşif tarihindeki şok edici olayları' → boş; 'bilim tarihi ilginç'
    → dolu).

    ``keywords`` artık KISA DEVRE YAPMAZ, LLM'e İPUCU olur. Eskiden keywords doluysa
    fonksiyon TEK sorgu döndürüp LLM'e HİÇ gitmiyordu — arama havuzu tek sorguya
    iniyordu ve niş hızla tükeniyordu.

    ``rotate``: her yenilemede FARKLI bir alt küme aransın diye kaydırma. Aynı sorgular
    YouTube'dan aynı videoları getiriyor; bankada zaten olan videolar elenince geriye
    çok az yeni kanıt kalıyordu (ölçüldü: 10 konudan 8'i mükerrer).
    """
    kw = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    short = _short_query(niche_query)
    fallback = ([" ".join(kw[:3])] if kw
                else ([" ".join(short.split()[:3])] if short else ["ilginç bilgiler"]))
    if llm_call is None:
        return fallback

    lang = _LANG_NAMES_Q.get(language, "Türkçe")
    ipucu = f'\nKANAL ANAHTAR KELİMELERİ (ipucu): {", ".join(kw[:6])}' if kw else ""
    try:
        v = run_json(
            f'Şu YouTube Shorts nişi için {_QUERY_POOL} KISA arama sorgusu üret. '
            f'Her biri 2-3 yaygın {lang} kelime; talimat değil ARAMA TERİMİ.\n'
            f'ÖNEMLİ: sorgular nişin FARKLI KÖŞELERİNİ taramalı — birbirinin '
            f'eşanlamlısı olmasın. Aynı şeyi soran sorgular YouTube\'dan aynı '
            f'videoları getirir ve yeni kanıt bulunamaz.\n'
            f'SÖZDE-BİLİM MIKNATISLARI YASAK: "doğal şifa", "mucize kür", "detoks", '
            f'"bitkisel tedavi" gibi terimler alternatif tıp içeriği getirir — bilim '
            f'kanalına ÇÖP taşır. (Gerçek hata: "doğal şifa yolları" sorgusu bankaya '
            f'mistik şifa konusu soktu.) Sorgular SOMUT olguları hedeflesin: organ, '
            f'hücre, mekanizma, ölçülebilir olay.\n'
            f'NİŞ: "{short}"{ipucu}\n'
            f'SADECE JSON: {{"queries": ["...", "...", "..."]}}',
            _SearchQueries, claude_path=llm_call.claude_path, model=llm_call.model,
            backend=llm_call.backend, api_key=llm_call.api_key,
            retries=1, timeout_s=60)
        out = [q.strip() for q in v.queries if (q or "").strip()][:_QUERY_POOL]
    except Exception as e:   # noqa: BLE001 — sorgu üretimi kritik değil
        log.info(f"topic_miner: sorgu türetme atlandı ({e}) → fallback")
        return fallback
    if not out:
        return fallback

    # DÖNÜŞÜMLÜ alt küme: her yenileme nişin farklı köşesine bakar.
    n = min(_QUERY_USE, len(out))
    secili = [out[(int(rotate) + i) % len(out)] for i in range(n)]
    log.info(f"topic_miner: {len(out)} sorgu üretildi, {n} tanesi aranıyor "
             f"(kaydırma {rotate}): {secili}")
    return secili


# Kademeli outlier eşikleri: sıkı geçmezse gevşet (hiç sonuç > mükemmel sonuç).
# Havuz API'den BİR kez ham çekilir; kademeler YERELDE uygulanır (ekstra birim yok).
_FILTER_TIERS = (
    {"min_views": 20_000, "max_subs": 500_000, "min_ratio": 3.0},   # sıkı (gerçek outlier)
    {"min_views": 10_000, "max_subs": 2_000_000, "min_ratio": 1.0},
    {"min_views": 5_000, "max_subs": 10**9, "min_ratio": 0.0},
)


def _apply_tier(rows: list[dict], tier: dict) -> list[dict]:
    return [r for r in rows
            if r["views"] >= tier["min_views"] and r["subs"] <= tier["max_subs"]
            and r["ratio"] >= tier["min_ratio"]]


def _drop_known(rows: list[dict], known: set[str]) -> list[dict]:
    """Bankada ZATEN olan videoları ele.

    BU ELEMENİN YERİ HAYATİ. Eskiden damıtmadan SONRA yapılıyordu: havuzdan en iyi 12
    video seçiliyor, LLM 12'sini de damıtıyor, sonra bankada olanlar atılıyordu.
    ÖLÇÜLDÜ: damıtılan 10 konunun 8'i zaten bankadaki videolardan geliyordu → yalnız
    2 yeni konu. LLM bütçesinin %80'i çöpe gidiyordu.
    """
    if not known:
        return rows
    return [r for r in rows
            if (r.get("source_title") or "").strip().lower() not in known]


def mine_evidence(niche_query: str, *, api_keys: list, language: str = "tr",
                  anchor: str = "", llm_call=None, count: int = 12,
                  keywords=None, reference_channels=None,
                  exclude_sources=None, rotate: int = 0,
                  http_get=None) -> list[dict]:
    """YouTube outlier KANITI topla — konu ÜRETMEZ (o iş ``topic_propose``un).

    Dönen satırlar: ``{"source_title", "views", "subs", "ratio", "video_id", "ref"}``
    ``ref=True`` → referans kanalın kendi outlier'ı (format + kitle kanıtlı).

    TAZE OUTLIER YOKSA BOŞ LİSTE DÖNER — hata FIRLATMAZ. Eskiden ValueError fırlıyordu
    ve madencilik TAMAMEN duruyordu; artık üretim kanıtsız koşar (kanıt İLHAMDIR,
    zorunluluk değil).
    """
    from short_bot.yt_outliers import channel_outlier_shorts, search_outlier_shorts
    known = {str(s).strip().lower() for s in (exclude_sources or []) if str(s).strip()}

    # 0) Referans kanallar — en güçlü kanıt, havuzun başına (~3 birim/kanal).
    ref_rows, seen_ids = [], set()
    for ref in (reference_channels or [])[:10]:
        try:
            found = channel_outlier_shorts(ref, api_keys=api_keys, limit=count * 3,
                                           http_get=http_get)
        except Exception as e:   # noqa: BLE001 — bir kanal ötekileri durdurmasın
            log.info(f"topic_miner: referans kanal atlandı ({ref!r}): {e}")
            continue
        for r in found:
            if r["video_id"] not in seen_ids:
                seen_ids.add(r["video_id"])
                r["ref"] = True
                ref_rows.append(r)

    ref_ham = len(ref_rows)
    ref_rows = _drop_known(ref_rows, known)
    ref_rows.sort(key=lambda r: r.get("ratio", 0), reverse=True)
    if len(ref_rows) >= count:
        log.info(f"topic_miner: referans kanallar {ref_ham} outlier verdi, "
                 f"{ref_ham - len(ref_rows)} bilinen elendi → {len(ref_rows)} taze "
                 f"(arama atlanıyor, kota tasarrufu)")
        return ref_rows[:count * _EVIDENCE_OVERSAMPLE]

    # 1) Arama havuzu (HAM çek; kademeler yerelde — ekstra birim yakılmaz).
    queries = _search_queries(niche_query, language, llm_call, keywords=keywords,
                              rotate=rotate)
    if anchor and all(anchor.lower() != q.lower() for q in queries):
        queries.append(anchor)

    pool = []
    for q in queries[:4]:
        lang_q = "en" if (anchor and q == anchor) else language
        try:
            found = search_outlier_shorts(q, api_keys=api_keys, language=lang_q,
                                          limit=count * 4, http_get=http_get,
                                          min_views=1_000, max_subs=10**12,
                                          min_ratio=0.0)
        except Exception as e:   # noqa: BLE001 — kota/ağ: KANITSIZ devam ederiz
            log.info(f"topic_miner: '{q}' araması atlandı: {e}")
            continue
        for r in found:
            if r["video_id"] not in seen_ids:
                seen_ids.add(r["video_id"])
                r["ref"] = False
                pool.append(r)

    havuz_ham = len(pool)
    pool = _drop_known(pool, known)
    log.info(f"topic_miner: havuz {havuz_ham} video → {havuz_ham - len(pool)} bilinen "
             f"elendi → {len(pool)} taze")

    rows = []
    for tier in _FILTER_TIERS:
        rows = _apply_tier(pool, tier)
        if rows:
            break
        log.info("topic_miner: filtre kademesi gevşetiliyor (0 outlier)")
    rows.sort(key=lambda r: r.get("ratio", 0), reverse=True)

    # Referans satırları ÖNCE (format-kanıtlı), arama satırları tamamlar.
    return (ref_rows + rows)[:count * _EVIDENCE_OVERSAMPLE]


def refresh_topic_bank(eng, channel_slug: str, niche_query: str, *,
                       language: str = "tr", api_keys: list | None = None,
                       anchor: str = "", llm_call=None, llm=None, http_get=None,
                       keywords=None, reference_channels=None,
                       extra_guidance: str = "", **_compat) -> dict:
    """kanıt → öneri → doğrulama → dedup → insert.

    ``{"added": N, "skipped_dup": M, "rejected": R}``

    API ANAHTARI VE REFERANS KANAL İKİSİ DE OPSİYONEL:
      • ``api_keys`` yoksa madencilik atlanır → kanıtsız üretim (banka asla kurumaz)
      • taze outlier yoksa madenci boş liste döner → kanıtsız üretim
      • madencilik patlarsa (kota/ağ) LOGLANIR → kanıtsız üretim

    ``llm``: Sonnet çağırıcısı ``(prompt, schema) -> örnek``. YOKSA RuntimeError —
    mekanik fallback KALDIRILDI (ham başlığı konu yapmak, ölçülen çöpün kaynağıydı).
    ``llm_call``: arama SORGUSU üretimi için ucuz model (opsiyonel, kritik değil).
    """
    from short_bot.db import all_bank_topics, insert_bank_topics
    from short_bot.topic_propose import propose_topics, verify_topics

    bank = all_bank_topics(eng, channel_slug)
    existing = [r["topic"] for r in bank]
    # KAYNAK VİDEO ELEMESİ. Metin benzerliği yetmiyor: aynı videodan çıkarılan iki konu
    # FARKLI cümlelerle yazılıyor ve fuzzy oran eşiğin altında kalıyor. Aynı video =
    # aynı olgu.
    sources = {(r.get("source_title") or "").strip().lower()
               for r in bank if (r.get("source_title") or "").strip()}

    # 1) KANIT (opsiyonel)
    kanit: list[dict] = []
    if api_keys:
        try:
            kanit = mine_evidence(niche_query, api_keys=api_keys, language=language,
                                  anchor=anchor, llm_call=llm_call, http_get=http_get,
                                  keywords=keywords,
                                  reference_channels=reference_channels,
                                  exclude_sources=sources,
                                  # Her yenileme nişin FARKLI köşesine baksın.
                                  rotate=len(bank))
        except Exception as e:   # noqa: BLE001 — kanıt yoksa üretim YİNE koşar
            log.warning(f"topic_miner: kanıt madenciliği başarısız ({e}) → "
                        f"kanıtsız üretime geçiliyor")
    else:
        log.info("topic_miner: YouTube API anahtarı yok → kanıtsız üretim")

    # 2) ÖNERİ — kanıt İLHAM, zorunluluk değil.
    onerilen = propose_topics(niche_query, language=language, evidence=kanit,
                              existing=existing, count=12, llm=llm,
                              extra_guidance=extra_guidance)

    # 3) DOĞRULAMA KAPISI — prompt'a güvenmek YETMİYOR (ölçüldü).
    yargilar = verify_topics([t.topic for t in onerilen], language=language, llm=llm)
    gecen, dusen = [], 0
    for t, y in zip(onerilen, yargilar):
        if y.solid:
            gecen.append(t)
        else:
            dusen += 1
            log.info(f"topic_miner: konu ELENDİ ({y.reason}) → {t.topic[:60]}")
    if onerilen and not gecen:
        log.warning(f"topic_miner: {len(onerilen)} önerinin HİÇBİRİ doğrulamayı "
                    f"geçmedi — hiçbir konu eklenmedi")

    # 4) DEDUP + INSERT
    fresh, dup = [], 0
    for t in gecen:
        src = (t.source_title or "").strip().lower()
        if src and src in sources:
            dup += 1
            continue
        if any(fuzz.ratio(t.topic.lower(), e.lower()) > _DUP_THRESHOLD
               for e in existing):
            dup += 1
            continue
        existing.append(t.topic)      # aynı partide de tekrar önle
        if src:
            sources.add(src)
        fresh.append(t.model_dump())

    insert_bank_topics(eng, channel_slug, fresh)
    log.info(f"topic_miner: {len(fresh)} yeni konu eklendi "
             f"({dup} mükerrer, {dusen} doğrulamada elendi)")
    return {"added": len(fresh), "skipped_dup": dup, "rejected": dusen}
