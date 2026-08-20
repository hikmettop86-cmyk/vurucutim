"""youtubeAnalytics API v2 — daily metrics with 48-72h delay."""
from __future__ import annotations

from datetime import date

from googleapiclient.discovery import build


# subscribersGained + averageViewPercentage: beğeni/abone teşhisi (2026-07-16)
# gösterdi ki dönüşüm video başına 7x oynuyor — hangi videonun abone getirdiğini
# görmeden içerik kararı alınamaz. Not: averageViewPercentage Shorts'ta %100'ü
# aşabilir (loop izlenmeleri sayılır) — bu hata değil, güçlü pozitif sinyal.
_METRICS = ("views,estimatedMinutesWatched,averageViewDuration,"
            "subscribersGained,averageViewPercentage")


# ---------------------------------------------------------------------------
# TRAFİK KAYNAĞI + ARAMA TERİMLERİ
#
# NEDEN (2026-08-20): "trafiğin çoğu aramadan geliyor olabilir" varsayımını
# ÖLÇTÜK. Aslan Gündem, 28 gün, 10,19M izlenme:
#     SHORTS %96,4 · YT_SEARCH %2,4 (245K) · SUBSCRIBER %0,6 · RELATED %0,0
# Dört kanalda da arama payı %2,2–2,9 — yapısal bir sabit. AMA video YAŞINA
# göre ayırınca tablo değişiyor:
#     60+ gün önce yüklenenler : arama %17,3   (akış onları bıraktı, arama kaldı)
#     1–2 ay                   : arama  %0,9
#     son 7 gün                : arama  %3,8 ama MUTLAK olarak en büyük dilim
# Yani arama iki ayrı şey: (a) tazede canlı sorguyu yakalamak, (b) eskide kalan
# kuyruk. İkisi de başlık/etiket metnine bakar — bu modül o metni besleyecek
# gerçek sorguları getirir.
#
# API TUZAKLARI (sondalayarak öğrenildi, tahmin değil):
#   * insightTrafficSourceType + subscribersGained  → HTTP 400 "not supported"
#   * insightTrafficSourceDetail + estimatedMinutesWatched → HTTP 500
#     (yalnız `views` ile çalışıyor)
#   * dimensions=video + insightTrafficSourceType filtresi → HTTP 400
#     (video bazında kaynak dökümü ancak filters=video==TEK_ID ile alınır)
_TRAFFIC_METRICS = "views,estimatedMinutesWatched"


def fetch_traffic_sources(credentials, *, start_date: date,
                          end_date: date) -> dict[str, dict]:
    """Kanal genelinde trafik kaynağı dağılımı.

    ``{"YT_SEARCH": {"views": 245308, "watch_time_min": 18212.0}, …}``
    Boş sözlük = veri yok (yeni kanal) — çağıran taraf bunu hata saymamalı.
    """
    yta = build("youtubeAnalytics", "v2", credentials=credentials)
    resp = yta.reports().query(
        ids="channel==MINE",
        startDate=start_date.isoformat(),
        endDate=end_date.isoformat(),
        metrics=_TRAFFIC_METRICS,
        dimensions="insightTrafficSourceType",
        sort="-views",
    ).execute()
    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    idx = {name: i for i, name in enumerate(headers)}
    out: dict[str, dict] = {}
    for row in resp.get("rows", []) or []:
        src = row[idx["insightTrafficSourceType"]]
        out[src] = {
            "views": int(row[idx["views"]]) if "views" in idx else 0,
            "watch_time_min": (float(row[idx["estimatedMinutesWatched"]])
                               if "estimatedMinutesWatched" in idx else 0.0),
        }
    return out


def fetch_search_terms(credentials, *, start_date: date, end_date: date,
                       limit: int = 25) -> list[tuple[str, int]]:
    """İzleyicilerin bizi BULDUĞU gerçek arama dizeleri, izlenmeye göre azalan.

    ``[("galatasaray transfer", 25302), ("gs transfer", 14594), …]``

    Bu liste metadata yazarının sözlüğüdür: YouTube'un metni sorguyla
    eşleştirebildiği tek yer başlık/açıklama/etiket. Ölçüm gösterdi ki kazanan
    sorgular SORU değil VARLIK+NİYET kalıbı ("gs transfer son dakika") ve
    kısaltma ("gs") hiçbir başlığımızda geçmiyordu — 25K+ izlenmelik sorgu
    hacmi, metnimizde o kelime hiç bulunmadan geliyordu.

    NOT: yalnız `views` metriği desteklenir (bkz. yukarıdaki tuzak notu).
    """
    yta = build("youtubeAnalytics", "v2", credentials=credentials)
    resp = yta.reports().query(
        ids="channel==MINE",
        startDate=start_date.isoformat(),
        endDate=end_date.isoformat(),
        metrics="views",
        dimensions="insightTrafficSourceDetail",
        filters="insightTrafficSourceType==YT_SEARCH",
        maxResults=max(1, min(int(limit), 200)),
        sort="-views",
    ).execute()
    out: list[tuple[str, int]] = []
    for row in resp.get("rows", []) or []:
        term = str(row[0] or "").strip()
        if term:
            out.append((term, int(row[1])))
    return out


def fetch_video_analytics(credentials, *, start_date: date, end_date: date,
                          video_ids: list[str]) -> dict[str, dict]:
    """Per-video aggregated metrics for the date window.

    Returns {video_id: {watch_time_min, avg_view_duration_s, views_in_window,
    subscribers_gained, avg_view_percentage}}.
    """
    if not video_ids:
        return {}
    yta = build("youtubeAnalytics", "v2", credentials=credentials)
    filter_str = "video==" + ",".join(video_ids)
    resp = yta.reports().query(
        ids="channel==MINE",
        startDate=start_date.isoformat(),
        endDate=end_date.isoformat(),
        metrics=_METRICS,
        dimensions="video",
        filters=filter_str,
    ).execute()

    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    rows = resp.get("rows", [])
    if not rows:
        return {}

    idx = {name: i for i, name in enumerate(headers)}
    out: dict[str, dict] = {}
    for row in rows:
        vid = row[idx["video"]]
        out[vid] = {
            "watch_time_min": float(row[idx["estimatedMinutesWatched"]])
                              if "estimatedMinutesWatched" in idx else 0.0,
            "avg_view_duration_s": float(row[idx["averageViewDuration"]])
                                    if "averageViewDuration" in idx else 0.0,
            "views_in_window": int(row[idx["views"]])
                                if "views" in idx else 0,
            "subscribers_gained": int(row[idx["subscribersGained"]])
                                   if "subscribersGained" in idx else 0,
            "avg_view_percentage": float(row[idx["averageViewPercentage"]])
                                    if "averageViewPercentage" in idx else 0.0,
        }
    return out
