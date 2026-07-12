"""YouTube Data API v3 ile outlier-shorts madenciliği (NexLev'siz, bedava).

Çekirdek fikir: "küçük kanalda patlamış video = kanıtlanmış konu".
search.list (100 birim) → videos.list (1) → channels.list (1) ≈ 102 birim/arama;
anahtar başına günlük 10.000 birim → ~98 arama. ÇOKLU ANAHTAR desteklenir:
kota dolan anahtar (403) atlanır, sıradaki denenir → toplam kota anahtar
sayısıyla çarpılır. Başlangıç anahtarı güne göre kaydırılır (eşit aşınma).

Ağ katmanı ``http_get`` ile enjekte edilir (testler sahte uçlarla koşar).
"""
from __future__ import annotations

import logging
import os
from datetime import date

log = logging.getLogger(__name__)

_YT = "https://www.googleapis.com/youtube/v3"

# Outlier eşikleri: views>=MIN_VIEWS (kanıtlanmış ilgi), subs<=MAX_SUBS (küçük/orta
# kanal — içerik kendi başına tutmuş), ratio=views/subs>=MIN_RATIO (patlama oranı).
MIN_VIEWS = 20_000
MAX_SUBS = 500_000
MIN_RATIO = 3.0


class QuotaExhausted(RuntimeError):
    """Tüm YouTube API anahtarlarının günlük kotası dolu."""


def resolve_youtube_api_keys(secrets: dict) -> list[str]:
    """Çoklu anahtar çözümü: env YOUTUBE_API_KEY + youtube_api_keys listesi +
    tekil youtube_api_key birleşimi. Sıra korunur, boş/tekrar elenir."""
    out: list[str] = []
    for k in ([os.environ.get("YOUTUBE_API_KEY")]
              + list((secrets or {}).get("youtube_api_keys") or [])
              + [(secrets or {}).get("youtube_api_key")]):
        k = (k or "").strip()
        if k and k not in out:
            out.append(k)
    return out


def _get_with_rotation(path: str, params: dict, api_keys: list[str], *,
                       http_get, timeout: int = 20) -> dict:
    """GET'i anahtar rotasyonuyla dener: 403 (kota) → sıradaki anahtar.

    Başlangıç indeksi güne göre kayar (anahtarlar eşit aşınır). Tüm anahtarlar
    403 verirse QuotaExhausted; başka HTTP hatası RuntimeError."""
    if not api_keys:
        raise ValueError("YouTube API anahtarı yok (Ayarlar → YouTube Data API)")
    start = date.today().toordinal() % len(api_keys)
    ordered = api_keys[start:] + api_keys[:start]
    last_status = None
    for key in ordered:
        r = http_get(f"{_YT}/{path}", params={**params, "key": key},
                     timeout=timeout)
        if r.status_code == 200:
            return r.json() or {}
        last_status = r.status_code
        if r.status_code == 403:
            # kota/erişim — sıradaki anahtarı dene
            log.info(f"yt_outliers: anahtar 403 (kota?) → sıradaki denenecek")
            continue
        raise RuntimeError(f"YouTube API hata (HTTP {r.status_code}, {path})")
    if last_status == 403:
        raise QuotaExhausted(
            "Tüm YouTube API anahtarlarının günlük kotası dolu görünüyor — "
            "yarın sıfırlanır ya da Ayarlar'dan yeni anahtar ekleyin.")
    raise RuntimeError(f"YouTube API hata (HTTP {last_status})")


def search_outlier_shorts(query: str, *, api_keys: list[str],
                          language: str = "tr", limit: int = 12,
                          max_pool: int = 50, http_get=None,
                          min_views: int = MIN_VIEWS, max_subs: int = MAX_SUBS,
                          min_ratio: float = MIN_RATIO) -> list[dict]:
    """Nişte outlier shorts ara: yüksek-izlenme havuzu → küçük-kanal oran filtresi.

    Dönüş (ratio azalan): [{source_title, views, subs, ratio, video_id, channel_id}].
    Maliyet ≈ 102 birim (1 arama + 2 batch stats).
    """
    if http_get is None:
        import requests
        http_get = requests.get
    q = (query or "").strip()
    if not q:
        return []
    # 1) Arama: izlenmeye göre sıralı havuz (büyük-kanal önyargısını oran filtresi düzeltir)
    search = _get_with_rotation("search", {
        "part": "snippet", "q": q, "type": "video", "videoDuration": "short",
        "order": "viewCount", "maxResults": min(50, max(5, max_pool)),
        "relevanceLanguage": language, "safeSearch": "none",
    }, api_keys, http_get=http_get)
    items = search.get("items") or []
    vids, chans, meta = [], [], {}
    for it in items:
        vid = ((it.get("id") or {}).get("videoId") or "").strip()
        sn = it.get("snippet") or {}
        cid = (sn.get("channelId") or "").strip()
        if not vid or not cid:
            continue
        vids.append(vid); chans.append(cid)
        meta[vid] = {"source_title": sn.get("title") or "", "channel_id": cid}
    if not vids:
        return []
    # 2) Video istatistikleri (tek batch, 1 birim)
    vstats = _get_with_rotation("videos", {
        "part": "statistics", "id": ",".join(vids[:50]),
    }, api_keys, http_get=http_get)
    views = {}
    for it in (vstats.get("items") or []):
        try:
            views[it["id"]] = int((it.get("statistics") or {}).get("viewCount", 0))
        except (KeyError, ValueError, TypeError):
            continue
    # 3) Kanal aboneleri (tek batch, 1 birim)
    cstats = _get_with_rotation("channels", {
        "part": "statistics", "id": ",".join(sorted(set(chans))[:50]),
    }, api_keys, http_get=http_get)
    subs = {}
    for it in (cstats.get("items") or []):
        try:
            subs[it["id"]] = int((it.get("statistics") or {}).get("subscriberCount", 0))
        except (KeyError, ValueError, TypeError):
            continue
    # 4) Outlier filtresi + sıralama
    out = []
    for vid, m in meta.items():
        v = views.get(vid, 0)
        s = subs.get(m["channel_id"], 0)
        if v < min_views or s <= 0 or s > max_subs:
            continue
        ratio = v / max(s, 100)
        if ratio < min_ratio:
            continue
        out.append({"source_title": m["source_title"], "views": v, "subs": s,
                    "ratio": round(ratio, 2), "video_id": vid,
                    "channel_id": m["channel_id"]})
    out.sort(key=lambda r: r["ratio"], reverse=True)
    return out[:limit]
