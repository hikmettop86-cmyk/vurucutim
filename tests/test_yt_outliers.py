import pytest

from short_bot.yt_outliers import (QuotaExhausted, resolve_youtube_api_keys,
                                   search_outlier_shorts)


def test_resolve_keys_merges_list_and_single(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    secrets = {"youtube_api_keys": ["K1", "K2"], "youtube_api_key": "K3"}
    assert resolve_youtube_api_keys(secrets) == ["K1", "K2", "K3"]
    # dup elenir, sıra korunur
    secrets = {"youtube_api_keys": ["K1", "K3"], "youtube_api_key": "K3"}
    assert resolve_youtube_api_keys(secrets) == ["K1", "K3"]
    assert resolve_youtube_api_keys({}) == []
    # env öne geçer
    monkeypatch.setenv("YOUTUBE_API_KEY", "ENV")
    assert resolve_youtube_api_keys({"youtube_api_key": "K3"}) == ["ENV", "K3"]


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _fake_yt(quota_dead_keys=()):
    """search/videos/channels uçlarını taklit eden http_get.

    Kota-ölü anahtarlar 403 döner (rotasyon testi). Kurgu: 3 video —
    v1: 2M izl / 5K abone (dev outlier), v2: 100K izl / 2M abone (büyük kanal,
    elenir), v3: 5K izl / 1K abone (izlenme az, elenir).
    """
    calls = {"keys": []}

    def http_get(url, params=None, timeout=None):
        key = (params or {}).get("key", "")
        calls["keys"].append(key)
        if key in quota_dead_keys:
            return _Resp(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})
        if "/search" in url:
            return _Resp(200, {"items": [
                {"id": {"videoId": f"v{i}"},
                 "snippet": {"title": f"Title {i}", "channelId": f"c{i}"}}
                for i in (1, 2, 3)]})
        if "/videos" in url:
            stats = {"v1": 2_000_000, "v2": 100_000, "v3": 5_000}
            return _Resp(200, {"items": [
                {"id": vid, "statistics": {"viewCount": str(n)}}
                for vid, n in stats.items()]})
        if "/channels" in url:
            subs = {"c1": 5_000, "c2": 2_000_000, "c3": 1_000}
            return _Resp(200, {"items": [
                {"id": cid, "statistics": {"subscriberCount": str(n)}}
                for cid, n in subs.items()]})
        return _Resp(404, {})
    return http_get, calls


def test_search_outliers_filters_and_ranks():
    http_get, _ = _fake_yt()
    rows = search_outlier_shorts("whale facts", api_keys=["K1"], http_get=http_get)
    assert [r["source_title"] for r in rows] == ["Title 1"]   # sadece gerçek outlier
    r = rows[0]
    assert r["views"] == 2_000_000 and r["subs"] == 5_000
    assert r["ratio"] > 100


def test_quota_rotation_fails_over_to_next_key(monkeypatch):
    # gün-indeksli başlangıcı sabitle: start=0 → DEAD ilk denenir → OK'a düşer
    import short_bot.yt_outliers as yo

    class _D:
        @staticmethod
        def today():
            class _T:
                @staticmethod
                def toordinal():
                    return 0
            return _T()
    monkeypatch.setattr(yo, "date", _D)
    http_get, calls = _fake_yt(quota_dead_keys=("DEAD",))
    rows = search_outlier_shorts("whale", api_keys=["DEAD", "OK"], http_get=http_get)
    assert rows                                   # ikinci anahtarla başardı
    assert "DEAD" in calls["keys"] and "OK" in calls["keys"]


def test_all_keys_exhausted_raises():
    http_get, _ = _fake_yt(quota_dead_keys=("D1", "D2"))
    with pytest.raises(QuotaExhausted):
        search_outlier_shorts("whale", api_keys=["D1", "D2"], http_get=http_get)


def test_no_keys_raises():
    with pytest.raises(ValueError, match="anahtar"):
        search_outlier_shorts("whale", api_keys=[])


# ── Referans-kanal madenciliği ────────────────────────────────────────────────

def test_parse_channel_ref_forms():
    from short_bot.yt_outliers import parse_channel_ref
    assert parse_channel_ref("https://www.youtube.com/@BilimleBak/shorts") == \
        ("handle", "BilimleBak")
    assert parse_channel_ref("@BilimleBak") == ("handle", "BilimleBak")
    assert parse_channel_ref("BilimleBak") == ("handle", "BilimleBak")
    assert parse_channel_ref(
        "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv/videos") == \
        ("id", "UCabcdefghijklmnopqrstuv")
    assert parse_channel_ref("UCabcdefghijklmnopqrstuv") == \
        ("id", "UCabcdefghijklmnopqrstuv")
    assert parse_channel_ref("") is None
    assert parse_channel_ref("ht!tp:@@bozuk url") is None


def test_iso_duration():
    from short_bot.yt_outliers import _iso_duration_s
    assert _iso_duration_s("PT45S") == 45
    assert _iso_duration_s("PT1M23S") == 83
    assert _iso_duration_s("PT1H2M3S") == 3723
    assert _iso_duration_s("bozuk") == 0


def _fake_channel_yt():
    """channels/playlistItems/videos uçları: 6 shorts (medyan 10K) + 1 uzun video.

    v1: 100K izl (10x medyan → outlier), v2..v6: ~10K (normal), v7: uzun (elenir).
    """
    def http_get(url, params=None, timeout=None):
        class _R:
            status_code = 200
            def __init__(self, p): self._p = p
            def json(self): return self._p
        if "/channels" in url:
            return _R({"items": [{
                "contentDetails": {"relatedPlaylists": {"uploads": "UUx"}},
                "statistics": {"subscriberCount": "50000"}}]})
        if "/playlistItems" in url:
            return _R({"items": [
                {"contentDetails": {"videoId": f"v{i}"},
                 "snippet": {"title": f"Short {i}"}} for i in range(1, 8)]})
        if "/videos" in url:
            stats = {"v1": 100_000, "v2": 9_000, "v3": 10_000, "v4": 11_000,
                     "v5": 10_500, "v6": 9_500, "v7": 500_000}
            return _R({"items": [
                {"id": vid,
                 "statistics": {"viewCount": str(n)},
                 "contentDetails": {"duration": "PT10M" if vid == "v7" else "PT40S"}}
                for vid, n in stats.items()]})
        return _R({})
    return http_get


def test_channel_outlier_shorts_median_based():
    from short_bot.yt_outliers import channel_outlier_shorts
    rows = channel_outlier_shorts("https://www.youtube.com/@X/shorts",
                                  api_keys=["K"], http_get=_fake_channel_yt())
    assert [r["source_title"] for r in rows] == ["Short 1"]   # yalnız 10x patlama
    assert rows[0]["views"] == 100_000 and rows[0]["subs"] == 50_000
    assert rows[0]["ratio"] >= 9                              # views/medyan
    assert rows[0]["ref_channel"].endswith("@X/shorts")
    # uzun video (v7) medyana ve outlier'a hiç girmedi


def test_channel_outlier_unknown_ref_returns_empty():
    from short_bot.yt_outliers import channel_outlier_shorts
    def http_get(url, params=None, timeout=None):
        class _R:
            status_code = 200
            def json(self): return {"items": []}
        return _R()
    assert channel_outlier_shorts("@yok", api_keys=["K"], http_get=http_get) == []
