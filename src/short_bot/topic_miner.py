"""Kanıtlanmış-konu madencisi: nişte patlamış shorts → konu bankası.

Backend: **YouTube Data API v3** (``yt_outliers`` — bedava 10K birim/gün ×
anahtar sayısı, saniyeler içinde biter). NexLev bağımlılığı 2026-07-12'de
KALDIRILDI (claude-CLI köprüsü + OAuth + 10 arama/gün kotası + 4-9 dk sorgular).

Akış: kısa arama sorguları (kanal keywords → LLM türetimi → ilk-3-kelime) →
outlier havuzu (küçük kanalda patlamış = kanıtlanmış konu) → kademeli filtre →
LLM tek çağrıyla hedef dile damıtma. Üretim anında ÇAĞRILMAZ — panel düğmesi +
haftalık cron doldurur, üretim ``db.active_bank_topics`` okur.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel
from rapidfuzz import fuzz

from short_bot.claude_cli import run_json

log = logging.getLogger(__name__)

_DUP_THRESHOLD = 80   # aynı kanaldaki mevcut konuya fuzzy oran eşiği

_LANG_NAMES = {"tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
               "es": "İspanyolca", "fr": "Fransızca"}


def _short_query(niche_query: str, max_len: int = 90) -> str:
    """Uzun/talimatlı kanal konusunu kısa niş sorgusuna indir.

    generator.topic tam bir yönerge olabilir ("...gerilim kurarak anlat") —
    aramaya talimat değil NİŞ lazım; ilk cümle/iki-nokta öncesi + uzunluk katı."""
    q = (niche_query or "").strip()
    for sep in ("—", ":", ".", "\n"):
        head = q.split(sep)[0].strip()
        if len(head) >= 20:
            q = head
    return q[:max_len]


class _MinedTopic(BaseModel):
    topic: str
    source_title: str = ""
    views: int = 0
    subs: int = 0
    hook_pattern: str = ""


class _MinedTopics(BaseModel):
    topics: list[_MinedTopic]


def _distill_prompt(rows: list[dict], lang: str) -> str:
    lines = "\n".join(
        f"- \"{r['source_title']}\"  ({r['views']:,} izlenme / {r['subs']:,} abone)"
        for r in rows)
    return f"""Aşağıda bir YouTube nişinde KÜÇÜK kanallarda patlamış (outlier)
shorts başlıkları var. Her birini {lang} tek cümlelik VİDEO KONUSU fikrine damıt
ve başlığın örüntüsünü çıkar. views/subs değerlerini AYNEN kopyala.

{lines}

SADECE JSON: {{"topics": [{{"topic": "<{lang} konu fikri>",
  "source_title": "<orijinal başlık>", "views": <int>, "subs": <int>,
  "hook_pattern": "<{lang} 2-4 kelime örüntü, ör. 'sayı + beklenmedik iddia'>"}}]}}"""


class _SearchQueries(BaseModel):
    queries: list[str]


def _search_queries(niche_query: str, language: str, llm_call,
                    keywords=None) -> list[str]:
    """Nişten 2-3 KISA YouTube arama sorgusu üret.

    Uzun/talimatlı niş cümlesi YouTube aramasında 0 sonuç veriyor (gerçek ölçüm:
    'Bilim ve keşif tarihindeki şok edici olayları' → boş; 'bilim tarihi ilginç'
    → dolu). Öncelik: kanal keywords → LLM türetimi → ilk-3-kelime fallback."""
    kw = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    if kw:
        return [" ".join(kw[:3])]
    short = _short_query(niche_query)
    fallback = [" ".join(short.split()[:3])] if short else ["ilginç bilgiler"]
    if llm_call is None:
        return fallback
    lang = _LANG_NAMES.get(language, "Türkçe")
    try:
        v = run_json(
            f'Şu YouTube Shorts nişi için 2-3 KISA arama sorgusu üret '
            f'(her biri 2-3 yaygın {lang} kelime; talimat değil, arama terimi): '
            f'"{short}"\nSADECE JSON: {{"queries": ["...", "..."]}}',
            _SearchQueries, claude_path=llm_call.claude_path, model=llm_call.model,
            backend=llm_call.backend, api_key=llm_call.api_key,
            retries=1, timeout_s=60)
        out = [q.strip() for q in v.queries if (q or "").strip()][:3]
        return out or fallback
    except Exception as e:
        log.info(f"topic_miner: sorgu türetme atlandı ({e}) → fallback")
        return fallback


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


def mine_topics_via_api(niche_query: str, *, api_keys: list, language: str = "tr",
                        anchor: str = "", llm_call=None, count: int = 12,
                        keywords=None, http_get=None) -> list[dict]:
    """YouTube Data API ile outlier madenciliği (~102 birim/arama).

    Akış: kısa arama sorguları (keywords/LLM) → outlier havuzu (+ EN çıpa) →
    kademeli filtre → LLM tek çağrıyla {lang} konu fikrine damıtma. ``llm_call``
    yoksa mekanik fallback: başlık aynen topic olur (üretim durmaz).
    """
    from short_bot.yt_outliers import search_outlier_shorts
    queries = _search_queries(niche_query, language, llm_call, keywords=keywords)
    if anchor and all(anchor.lower() != q.lower() for q in queries):
        queries.append(anchor)
    # Havuzu HAM çek (filtre yok) — kademeler yerelde uygulanır, ekstra birim yakılmaz.
    pool, seen_ids = [], set()
    for qi, q in enumerate(queries[:4]):
        lang_q = "en" if (anchor and q == anchor) else language
        try:
            found = search_outlier_shorts(q, api_keys=api_keys, language=lang_q,
                                          limit=count * 4, http_get=http_get,
                                          min_views=1_000, max_subs=10**12,
                                          min_ratio=0.0)
        except Exception as e:
            if qi == 0 and not pool:
                raise   # ilk arama bile yoksa (kota/ağ) net hata
            log.info(f"topic_miner: '{q}' araması atlandı: {e}")
            continue
        for r in found:
            if r["video_id"] not in seen_ids:
                seen_ids.add(r["video_id"]); pool.append(r)
    rows = []
    for tier in _FILTER_TIERS:
        rows = _apply_tier(pool, tier)
        if rows:
            break
        log.info("topic_miner: filtre kademesi gevşetiliyor (0 outlier)")
    rows.sort(key=lambda r: r.get("ratio", 0), reverse=True)
    rows = rows[:count]
    if not rows:
        raise ValueError("YouTube API'de bu niş için outlier bulunamadı")
    if llm_call is None:
        return [{"topic": r["source_title"], "source_title": r["source_title"],
                 "views": r["views"], "subs": r["subs"], "hook_pattern": ""}
                for r in rows]
    lang = _LANG_NAMES.get(language, "Türkçe")
    v = run_json(_distill_prompt(rows, lang), _MinedTopics,
                 claude_path=llm_call.claude_path, model=llm_call.model,
                 backend=llm_call.backend, api_key=llm_call.api_key,
                 retries=2, timeout_s=120)
    out = [t.model_dump() for t in v.topics if (t.topic or "").strip()]
    if not out:
        raise ValueError("damıtma boş döndü")
    return out[:count]


def refresh_topic_bank(eng, channel_slug: str, niche_query: str, *,
                       language: str = "tr", api_keys: list | None = None,
                       anchor: str = "", llm_call=None, http_get=None,
                       keywords=None, **_compat) -> dict:
    """mine → mevcut bankaya fuzzy-dedup → insert. {"added": N, "skipped_dup": M}.

    Tek backend: YouTube Data API (``api_keys`` zorunlu — yoksa net Türkçe hata;
    kota dolarsa ``yt_outliers.QuotaExhausted`` mesajı yüzeye çıkar).
    ``**_compat`` eski çağıranların claude_path/model/run/backend argümanlarını
    sessizce yutar (NexLev kaldırıldı).
    """
    from short_bot.db import all_bank_topics, insert_bank_topics
    if not api_keys:
        raise RuntimeError("YouTube API anahtarı yok — Ayarlar → YouTube Data "
                           "API bölümünden anahtar ekleyin.")
    mined = mine_topics_via_api(niche_query, api_keys=api_keys,
                                language=language, anchor=anchor,
                                llm_call=llm_call, http_get=http_get,
                                keywords=keywords)
    log.info(f"topic_miner: youtube_api → {len(mined)} konu")
    existing = [r["topic"] for r in all_bank_topics(eng, channel_slug)]
    fresh, dup = [], 0
    for r in mined:
        if any(fuzz.ratio(r["topic"].lower(), e.lower()) > _DUP_THRESHOLD
               for e in existing):
            dup += 1
            continue
        existing.append(r["topic"])   # aynı partide de tekrar önle
        fresh.append(r)
    insert_bank_topics(eng, channel_slug, fresh)
    return {"added": len(fresh), "skipped_dup": dup}
