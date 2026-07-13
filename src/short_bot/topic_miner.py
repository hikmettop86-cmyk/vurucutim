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


# Damıtma çıktısında video-TARİFİ kalıpları (konu değil meta-açıklama) — yasak.
# Gerçek üretim hatası (2026-07-12): "…tanıtan bir seri", "…ele alan bir skeç".
_META_WORDS = ("video", "belgesel", "seri", "skeç", "inceleme", "anlatım",
               "sunum", "içerik", "tanıtan", "anlatan", "özetleyen",
               "ele alan", "konu alan", "keşfeden bir", "yolculuğu")


def _drop_meta_topics(rows: list[dict]) -> list[dict]:
    """Video-tarifi üretilmiş kayıtları ele (topic bir İDDİA olmalı)."""
    out = []
    for r in rows:
        low = (r.get("topic") or "").lower()
        if any(w in low for w in _META_WORDS):
            continue
        out.append(r)
    return out


def _distill_prompt(rows: list[dict], lang: str) -> str:
    lines = "\n".join(
        f"- \"{r['source_title']}\"  ({r['views']:,} izlenme / {r['subs']:,} abone)"
        for r in rows)
    return f"""Aşağıda bir YouTube nişinde KÜÇÜK kanallarda patlamış (outlier)
shorts başlıkları var. Her başlıktan {lang} dilinde TEK ÇARPICI İDDİA/GERÇEK
cümlesi çıkar — bir shorts videosunun KONUSU olacak.

KURALLAR (ÇOK ÖNEMLİ):
- topic bir İDDİA ya da ŞAŞIRTICI GERÇEK cümlesidir; videoyu TARİF ETMEZ.
  Şu kalıplar KESİNLİKLE YASAK: "…anlatan/tanıtan/özetleyen/ele alan/konu alan
  bir video/seri/belgesel/skeç/inceleme/anlatım/sunum".
  KÖTÜ: "Einstein'ın beynini konu alan bir inceleme"
  İYİ:  "Einstein'ın beyni ölümünden sonra izinsiz çalındı ve 40 yıl kavanozda gezdirildi"
  KÖTÜ: "İnsan evrimini 40 saniyede özetleyen görsel bir anlatım"
  İYİ:  "6 milyon yıllık insan evriminde vücudumuzda hâlâ duran 3 işe yaramaz organ"
- Başlık bir liste/derleme ise ("Top 10…", "Famous Scientists…") içinden EN
  çarpıcı TEK gerçeği seç ve iddiaya çevir.
- FORMAT UYUMU (EN ÖNEMLİ ELEME): konu, stok görüntü + seslendirmeyle anlatılan
  40 saniyelik faceless "ilginç bilgi" videosuna uymalı — yani TEK, DOĞRULANABİLİR,
  şaşırtıcı GERÇEK. Şunları ATLA: film/dizi özetleri ve kurgu sahneler, aşk/dram
  hikâyeleri ve kişi-odaklı anlatılar (ör. "X ile Y'nin aşkı imparatorluğu nasıl
  değiştirdi"), vlog/tepki/meme içerikleri, hikâye anlatımı gerektiren konular.
  Test: izleyici 40 saniyede "vay be, bunu bilmiyordum" diyebilecek mi? Hayırsa ATLA.
- HEDEF KİTLE: {lang} konuşan GENEL izleyici. Konu onun merakını çekmeli —
  evrensel merak (uzay, insan vücudu, tarihin şok anları, gizemler) İYİ;
  fazla akademik/teknik konular (ör. "Mock Theta Fonksiyonu"), başka ülkeye
  özgü yerel içerik/mizah, tanınmayan kişiler → o kaydı ATLA.
- Başlık nişe alakasız, anlamsız ya da hedef dile çevrilemeyecek kadar belirsizse
  o kaydı ATLA (çıktıya koyma).
- views/subs değerlerini kaynaktan AYNEN kopyala.

{lines}

SADECE JSON: {{"topics": [{{"topic": "<{lang} tek çarpıcı iddia cümlesi>",
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
                        keywords=None, reference_channels=None,
                        http_get=None) -> list[dict]:
    """YouTube Data API ile outlier madenciliği.

    Akış: (0) OPSİYONEL referans kanallar — kanalın KENDİ medyanına göre patlayan
    shorts'lar (format+kitle garantili, ~3 birim/kanal, tier filtresine girmez;
    yeterse arama hiç yapılmaz) → (1) kısa arama sorguları (keywords/LLM) →
    outlier havuzu (+ EN çıpa, ~102 birim/arama) → kademeli filtre → LLM tek
    çağrıyla {lang} konu fikrine damıtma. ``llm_call`` yoksa mekanik fallback:
    başlık aynen topic olur (üretim durmaz).
    """
    from short_bot.yt_outliers import channel_outlier_shorts, search_outlier_shorts
    # 0) Referans kanallar — kanıt en güçlü kaynak, havuzun başına.
    ref_rows, seen_ids = [], set()
    for ref in (reference_channels or [])[:10]:
        try:
            found = channel_outlier_shorts(ref, api_keys=api_keys, limit=count,
                                           http_get=http_get)
        except Exception as e:
            log.info(f"topic_miner: referans kanal atlandı ({ref!r}): {e}")
            continue
        for r in found:
            if r["video_id"] not in seen_ids:
                seen_ids.add(r["video_id"]); ref_rows.append(r)
    ref_rows.sort(key=lambda r: r.get("ratio", 0), reverse=True)
    if len(ref_rows) >= count:
        log.info(f"topic_miner: referans kanallar {len(ref_rows)} outlier verdi "
                 f"→ arama atlanıyor (kota tasarrufu)")
        rows = ref_rows[:count]
        return _distill(rows, language, llm_call, count)
    # 1) Arama havuzu (HAM çek; kademeler yerelde — ekstra birim yakılmaz).
    queries = _search_queries(niche_query, language, llm_call, keywords=keywords)
    if anchor and all(anchor.lower() != q.lower() for q in queries):
        queries.append(anchor)
    pool = []
    for qi, q in enumerate(queries[:4]):
        lang_q = "en" if (anchor and q == anchor) else language
        try:
            found = search_outlier_shorts(q, api_keys=api_keys, language=lang_q,
                                          limit=count * 4, http_get=http_get,
                                          min_views=1_000, max_subs=10**12,
                                          min_ratio=0.0)
        except Exception as e:
            if qi == 0 and not pool and not ref_rows:
                raise   # hiçbir kaynak yoksa (kota/ağ) net hata
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
    # Referans satırları ÖNCE (format-kanıtlı), arama satırları tamamlar.
    rows = (ref_rows + rows)[:count]
    if not rows:
        raise ValueError("YouTube API'de bu niş için outlier bulunamadı")
    return _distill(rows, language, llm_call, count)


def _distill(rows: list[dict], language: str, llm_call, count: int) -> list[dict]:
    """Outlier satırlarını LLM ile hedef-dil konu iddialarına damıt (ya da mekanik)."""
    if llm_call is None:
        return [{"topic": r["source_title"], "source_title": r["source_title"],
                 "views": r["views"], "subs": r["subs"], "hook_pattern": ""}
                for r in rows]
    lang = _LANG_NAMES.get(language, "Türkçe")
    prompt = _distill_prompt(rows, lang)
    v = run_json(prompt, _MinedTopics,
                 claude_path=llm_call.claude_path, model=llm_call.model,
                 backend=llm_call.backend, api_key=llm_call.api_key,
                 retries=2, timeout_s=120)
    out = _drop_meta_topics(
        [t.model_dump() for t in v.topics if (t.topic or "").strip()])
    if not out:
        # LLM yine video-TARİFİ üretti — bir kez düzeltici uyarıyla tekrar dene.
        log.info("topic_miner: damıtma meta-tarif üretti → düzeltici retry")
        v = run_json(prompt + "\n\nUYARI: Önceki denemede video TARİFİ ürettin "
                     "('…anlatan bir video' gibi). SADECE İDDİA cümleleri yaz.",
                     _MinedTopics, claude_path=llm_call.claude_path,
                     model=llm_call.model, backend=llm_call.backend,
                     api_key=llm_call.api_key, retries=1, timeout_s=120)
        out = _drop_meta_topics(
            [t.model_dump() for t in v.topics if (t.topic or "").strip()])
    if not out:
        raise ValueError("damıtma kullanılabilir konu üretemedi (meta-tarif)")
    return out[:count]


def refresh_topic_bank(eng, channel_slug: str, niche_query: str, *,
                       language: str = "tr", api_keys: list | None = None,
                       anchor: str = "", llm_call=None, http_get=None,
                       keywords=None, reference_channels=None, **_compat) -> dict:
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
                                keywords=keywords,
                                reference_channels=reference_channels)
    log.info(f"topic_miner: youtube_api → {len(mined)} konu")
    bank = all_bank_topics(eng, channel_slug)
    existing = [r["topic"] for r in bank]
    # KAYNAK VİDEO ELEMESİ. Metin benzerliği yetmiyor: aynı videodan damıtılan iki
    # konu FARKLI cümlelerle yazılıyor ("Sigara içtiğinizde her organ toksik hasar
    # görür" / "Sigara içtiğinizde yıkıcı bir reaksiyon başlar") ve fuzzy oran
    # eşiğin altında kalıyor — bankada aynı olgunun iki kaydı birikiyordu (gerçek
    # durum: üç mükerrer çift). Aynı video = aynı olgu; bir tanesi yeter.
    sources = {(r.get("source_title") or "").strip().lower()
               for r in bank if (r.get("source_title") or "").strip()}
    fresh, dup = [], 0
    for r in mined:
        src = (r.get("source_title") or "").strip().lower()
        if src and src in sources:
            dup += 1
            continue
        if any(fuzz.ratio(r["topic"].lower(), e.lower()) > _DUP_THRESHOLD
               for e in existing):
            dup += 1
            continue
        existing.append(r["topic"])   # aynı partide de tekrar önle
        if src:
            sources.add(src)
        fresh.append(r)
    insert_bank_topics(eng, channel_slug, fresh)
    return {"added": len(fresh), "skipped_dup": dup}
