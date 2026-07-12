"""NexLev kanıtlanmış-konu madencisi: nişte patlamış shorts → konu bankası.

TIMEOUT NOTU: NexLev MCP köprüsü niş karmaşıklığına göre 4-9 dk sürebilir
(gerçek ölçüm: balinalar ~4dk OK, bilim-tarihi 300s'te timeout). Varsayılan
600s; daha kısası gerçek nişlerde zaman aşımı üretir.

``web/niche_finder.py`` deseninin aynası: headless ``claude`` CLI, allowed-tools
NexLev outlier araçlarıyla kısıtlı, ``run=subprocess.run`` testlerde enjekte
edilir. Üretim anında ÇAĞRILMAZ — panel düğmesi + haftalık cron doldurur,
üretim ``db.active_bank_topics`` okur.
"""
from __future__ import annotations

import json
import logging
import subprocess

from pydantic import BaseModel
from rapidfuzz import fuzz

from short_bot.claude_cli import run_json

log = logging.getLogger(__name__)

_ALLOWED_TOOLS = ",".join([
    "mcp__claude_ai_NexLev__search_viral_videos_small_channels",
    "mcp__claude_ai_NexLev__youtube_channel_outliers",
    "mcp__claude_ai_NexLev__search_shorts_niche_finder_channels",
])

_DUP_THRESHOLD = 80   # aynı kanaldaki mevcut konuya fuzzy oran eşiği

_LANG_NAMES = {"tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
               "es": "İspanyolca", "fr": "Fransızca"}


def _short_query(niche_query: str, max_len: int = 90) -> str:
    """Uzun/talimatlı kanal konusunu kısa niş sorgusuna indir.

    generator.topic tam bir yönerge olabilir ("...gerilim kurarak anlat") —
    NexLev'e talimat değil NİŞ lazım; ilk cümle/iki-nokta öncesi + uzunluk katı.
    Uzun sorgu Claude'u sınırsız keşfe sürüklüyor (bilim kanalı 600s'te bile
    timeout; kısa sorguda balinalar ~4dk)."""
    q = (niche_query or "").strip()
    for sep in ("—", ":", ".", "\n"):
        head = q.split(sep)[0].strip()
        if len(head) >= 20:
            q = head
    return q[:max_len]


def _prompt(niche_query: str, count: int, lang: str) -> str:
    return f"""NexLev araçlarıyla şu nişte KÜÇÜK kanallarda PATLAMIŞ (outlier)
YouTube Shorts videolarını bul: "{niche_query}"

HIZLI OL: en fazla 3 NexLev arama çağrısı yap; derin inceleme yapma; ilk güçlü
sonuçlarla yetin.
Küçük kanal + çok izlenme = kanıtlanmış konu. En güçlü {count} videoyu seç.
Her biri için SADECE şu JSON dizisini döndür (başka metin YOK):
[{{"topic": "<{lang} tek cümlelik konu fikri — bu konuda video üretilecek>",
  "source_title": "<orijinal video başlığı>",
  "views": <videonun izlenmesi, int>,
  "subs": <kanalın abone sayısı, int>,
  "hook_pattern": "<başlığın örüntüsü, {lang} 2-4 kelime, ör. 'sayı + beklenmedik iddia'>"}}]"""


def _extract_json_array(text: str) -> list:
    """Model çıktısından JSON diziyi çıkar (kod bloğu/önek metne dayanıklı)."""
    text = (text or "").strip()
    try:
        val = json.loads(text)
        if isinstance(val, list):
            return val
    except (ValueError, TypeError):
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            val = json.loads(text[start:end + 1])
            if isinstance(val, list):
                return val
        except (ValueError, TypeError):
            pass
    raise ValueError("model çıktısında JSON dizi bulunamadı")


def _parse_topics(text: str) -> list[dict]:
    """Ham çıktı → normalize kayıt listesi (eksik alan coercion, boş topic elenir)."""
    out = []
    for item in _extract_json_array(text):
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue

        def _i(v):
            try:
                return int(str(v).replace(",", "").replace(".", "") or 0)
            except (ValueError, TypeError):
                return 0
        out.append({"topic": topic,
                    "source_title": str(item.get("source_title") or "").strip(),
                    "views": _i(item.get("views")), "subs": _i(item.get("subs")),
                    "hook_pattern": str(item.get("hook_pattern") or "").strip()})
    if not out:
        raise ValueError("geçerli konu kaydı çıkarılamadı")
    return out


def mine_topics(niche_query: str, *, language: str = "tr",
                claude_path: str = "claude", model: str | None = None,
                count: int = 12, timeout: int = 600,
                run=subprocess.run) -> list[dict]:
    """NexLev'den outlier shorts madenciliği. Hata → RuntimeError/ValueError."""
    niche_query = _short_query(niche_query) or "ilginç bilgiler"
    lang = _LANG_NAMES.get(language, "Türkçe")
    cmd = [claude_path, "-p", _prompt(niche_query, int(count), lang),
           "--allowedTools", _ALLOWED_TOOLS,
           "--output-format", "json",
           # Madencilik arama+özet işi — hızlı model yeterli; varsayılan (opus)
           # uzun agentic keşifte 600s'i aşıyor.
           "--model", model or "sonnet"]
    try:
        proc = run(cmd, capture_output=True, text=True,
                   timeout=timeout, encoding="utf-8")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"konu madenciliği zaman aşımına uğradı ({timeout}s)") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"claude CLI bulunamadı: {claude_path}") from e
    if getattr(proc, "returncode", 1) != 0:
        stderr = (getattr(proc, "stderr", "") or "")[:300]
        raise RuntimeError(f"claude CLI hata (kod {proc.returncode}): {stderr}")
    try:
        envelope = json.loads(proc.stdout)
        result_text = envelope.get("result", "") if isinstance(envelope, dict) else proc.stdout
    except (ValueError, TypeError):
        result_text = proc.stdout or ""
    try:
        return _parse_topics(result_text)
    except ValueError:
        # Teşhis: model JSON yerine ne döndürdü (kota/izin/düzyazı)?
        log.warning(f"topic_miner parse edilemedi; model çıktısı[:400]: "
                    f"{(result_text or '')[:400]!r}")
        low = (result_text or "").lower()
        if "kota" in low or "quota" in low or "limit" in low:
            # NexLev free plan günlük araması dolmuş — model bunu düzyazıyla
            # açıklıyor. Net Türkçe hata: kullanıcı panelde nedenini görsün.
            raise RuntimeError(
                "NexLev günlük arama kotası dolmuş görünüyor — yarın tekrar "
                "deneyin (free plan gün başına sınırlı arama verir).")
        raise


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
    """YouTube Data API ile outlier madenciliği (NexLev'siz, ~102 birim/arama).

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


def mine_topics_with_retry(niche_query: str, *, retries: int = 1, **kw) -> list[dict]:
    """mine_topics + parse-hatasında retry. Model bazen JSON yerine düzyazı
    döndürüyor (tek seferlik dalgalanma) — bir tekrar genellikle kurtarır."""
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            return mine_topics(niche_query, **kw)
        except ValueError as e:
            last = e
    raise last


def refresh_topic_bank(eng, channel_slug: str, niche_query: str, *,
                       language: str = "tr", claude_path: str = "claude",
                       model: str | None = None, run=subprocess.run,
                       api_keys: list | None = None, anchor: str = "",
                       llm_call=None, http_get=None, keywords=None,
                       backend: str = "auto") -> dict:
    """mine → mevcut bankaya fuzzy-dedup → insert. {"added": N, "skipped_dup": M}.

    Backend seçimi: ``api_keys`` varsa önce YouTube Data API (bedava 10K
    birim/gün × anahtar sayısı, saniyeler); o patlar ya da anahtar yoksa NexLev
    claude-CLI köprüsü (zengin ama kotalı/yavaş). ``backend="youtube_api"`` API'yi
    zorlar (fallback yok); ``"nexlev"`` doğrudan CLI.
    """
    from short_bot.db import all_bank_topics, insert_bank_topics
    mined = None
    if backend in ("auto", "youtube_api") and api_keys:
        try:
            mined = mine_topics_via_api(niche_query, api_keys=api_keys,
                                        language=language, anchor=anchor,
                                        llm_call=llm_call, http_get=http_get,
                                        keywords=keywords)
            log.info(f"topic_miner: youtube_api backend → {len(mined)} konu")
        except Exception as e:
            if backend == "youtube_api":
                raise
            log.warning(f"topic_miner: youtube_api başarısız ({e}) → NexLev'e düşülüyor")
    if mined is None:
        mined = mine_topics_with_retry(niche_query, language=language,
                                       claude_path=claude_path, model=model, run=run)
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
