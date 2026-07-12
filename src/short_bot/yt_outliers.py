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


def _err_reason(resp) -> str:
    try:
        errs = ((resp.json() or {}).get("error") or {}).get("errors") or []
        return str((errs[0] or {}).get("reason", "")) if errs else ""
    except Exception:
        return ""


def _get_with_rotation(path: str, params: dict, api_keys: list[str], *,
                       http_get, timeout: int = 20, sleep=None) -> dict:
    """GET'i anahtar rotasyonuyla dener: 403 kota → sıradaki anahtar; 403
    GEÇİCİ (rate/diğer) → kısa bekleyip aynı anahtarla 1 kez daha.

    Başlangıç indeksi güne göre kayar (anahtarlar eşit aşınır). Tüm anahtarlar
    kota-403 verirse QuotaExhausted; başka HTTP hatası RuntimeError."""
    if not api_keys:
        raise ValueError("YouTube API anahtarı yok (Ayarlar → YouTube Data API)")
    if sleep is None:
        import time
        sleep = time.sleep
    start = date.today().toordinal() % len(api_keys)
    ordered = api_keys[start:] + api_keys[:start]
    last_status = None
    for key in ordered:
        for attempt in (1, 2):
            r = http_get(f"{_YT}/{path}", params={**params, "key": key},
                         timeout=timeout)
            if r.status_code == 200:
                return r.json() or {}
            last_status = r.status_code
            if r.status_code != 403:
                raise RuntimeError(f"YouTube API hata (HTTP {r.status_code}, {path})")
            reason = _err_reason(r)
            if reason == "quotaExceeded":
                log.info("yt_outliers: anahtar kotası dolu → sıradaki denenecek")
                break   # bu anahtar bugünlük öldü → rotasyon
            # rate-limit/geçici 403 → kısa bekleyip aynı anahtarla tekrar
            if attempt == 1:
                log.info(f"yt_outliers: geçici 403 ({reason or '?'}) → 2s bekle, tekrar")
                sleep(2.0)
            else:
                log.info("yt_outliers: 403 sürüyor → sıradaki anahtar")
    if last_status == 403:
        raise QuotaExhausted(
            "Tüm YouTube API anahtarlarının günlük kotası dolu görünüyor — "
            "yarın sıfırlanır ya da Ayarlar'dan yeni anahtar ekleyin.")
    raise RuntimeError(f"YouTube API hata (HTTP {last_status})")


def parse_channel_ref(ref: str) -> "tuple[str, str] | None":
    """URL/@handle/UC-id → ('id'|'handle', değer). Anlaşılamazsa None.

    Kabul edilen biçimler: https://www.youtube.com/@X[/shorts], @X, X (handle
    varsayılır), https://www.youtube.com/channel/UC.../..., UC... (24 char id)."""
    import re
    s = (ref or "").strip()
    if not s:
        return None
    m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", s)
    if m:
        return ("id", m.group(1))
    if re.fullmatch(r"UC[\w-]{22}", s):
        return ("id", s)
    m = re.search(r"youtube\.com/@([\w.\-]+)", s)
    if m:
        return ("handle", m.group(1))
    if s.startswith("@"):
        return ("handle", s[1:])
    if re.fullmatch(r"[\w.\-]+", s):
        return ("handle", s)
    return None


def _iso_duration_s(iso: str) -> int:
    """ISO8601 süre → saniye (PT1M23S → 83). Bozuksa 0."""
    import re
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


# Shorts süresi üst sınırı (YouTube 2024+: 3 dk'ya kadar shorts olabilir).
SHORTS_MAX_S = 185
# Kanal-içi patlama eşiği: video, kanalın medyan izlenmesinin en az bu katı.
CHANNEL_OUTLIER_X = 3.0


def channel_outlier_shorts(channel_ref: str, *, api_keys: list[str],
                           limit: int = 12, min_views: int = 10_000,
                           http_get=None) -> list[dict]:
    """Referans kanalın KENDİ medyanına göre patlayan shorts'ları (~3 birim).

    Akış: kanal çöz (handle/id, 1 birim) → uploads playlist son 50 video
    (1 birim) → stats+süre (1 birim) → shorts'ları ayıkla → medyan izlenme →
    ``views >= CHANNEL_OUTLIER_X × medyan`` olanlar (ratio = views/medyan).
    Dönüş search_outlier_shorts ile aynı şekil (+``ref_channel`` alanı).
    """
    if http_get is None:
        import requests
        http_get = requests.get
    parsed = parse_channel_ref(channel_ref)
    if parsed is None:
        log.info(f"yt_outliers: referans kanal anlaşılamadı: {channel_ref!r}")
        return []
    kind, val = parsed
    params = {"part": "contentDetails,statistics"}
    params["id" if kind == "id" else "forHandle"] = val if kind == "id" else f"@{val}"
    ch = _get_with_rotation("channels", params, api_keys, http_get=http_get)
    items = ch.get("items") or []
    if not items:
        log.info(f"yt_outliers: referans kanal bulunamadı: {channel_ref!r}")
        return []
    info = items[0]
    uploads = (((info.get("contentDetails") or {}).get("relatedPlaylists") or {})
               .get("uploads") or "")
    try:
        subs = int((info.get("statistics") or {}).get("subscriberCount", 0))
    except (ValueError, TypeError):
        subs = 0
    if not uploads:
        return []
    pl = _get_with_rotation("playlistItems", {
        "part": "snippet,contentDetails", "playlistId": uploads, "maxResults": 50,
    }, api_keys, http_get=http_get)
    vids, titles = [], {}
    for it in (pl.get("items") or []):
        vid = ((it.get("contentDetails") or {}).get("videoId") or "").strip()
        if not vid:
            continue
        vids.append(vid)
        titles[vid] = ((it.get("snippet") or {}).get("title") or "")
    if not vids:
        return []
    vs = _get_with_rotation("videos", {
        "part": "statistics,contentDetails", "id": ",".join(vids[:50]),
    }, api_keys, http_get=http_get)
    shorts = []
    for it in (vs.get("items") or []):
        dur = _iso_duration_s(((it.get("contentDetails") or {}).get("duration")) or "")
        if not (0 < dur <= SHORTS_MAX_S):
            continue   # uzun video — shorts değil
        try:
            views = int((it.get("statistics") or {}).get("viewCount", 0))
        except (ValueError, TypeError):
            continue
        shorts.append((it.get("id"), views))
    if len(shorts) < 5:
        log.info(f"yt_outliers: {channel_ref!r} kanalında yeterli shorts yok "
                 f"({len(shorts)})")
        return []
    views_sorted = sorted(v for _, v in shorts)
    median = views_sorted[len(views_sorted) // 2] or 1
    out = []
    for vid, views in shorts:
        ratio = views / median
        if ratio < CHANNEL_OUTLIER_X or views < min_views:
            continue
        out.append({"source_title": titles.get(vid, ""), "views": views,
                    "subs": subs, "ratio": round(ratio, 2), "video_id": vid,
                    "channel_id": "", "ref_channel": channel_ref})
    out.sort(key=lambda r: r["ratio"], reverse=True)
    return out[:limit]


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
    # 1) Arama: izlenmeye göre sıralı havuz (büyük-kanal önyargısını oran filtresi
    # düzeltir). viewCount+short bazı sorgularda 0 döner → relevance'a düş.
    base = {"part": "snippet", "q": q, "type": "video", "videoDuration": "short",
            "maxResults": min(50, max(5, max_pool)),
            "relevanceLanguage": language, "safeSearch": "none"}
    search = _get_with_rotation("search", {**base, "order": "viewCount"},
                                api_keys, http_get=http_get)
    items = search.get("items") or []
    if not items:
        log.info("yt_outliers: viewCount havuzu boş → relevance denemesi")
        search = _get_with_rotation("search", {**base, "order": "relevance"},
                                    api_keys, http_get=http_get)
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
