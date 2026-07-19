"""reddit_gems: None-güvenli thumbnail/url çıkarımı (canlı demo regresyonu 2026-07-17).

GERÇEK HATA (canlı panel demosu): DEFAULT_SUBS taranınca bir postun thumbnail'ı None
geldi → `None.startswith('http')` çöktü ("'NoneType' object has no attribute
'startswith'") ve TÜM cevher çekimi düştü. .get(k, "") anahtar None DEĞERİYLE varsa
default'u DEĞİL None'ı döndürür — Reddit thumbnail'ı sık sık None/'default'/'nsfw'.
"""
from short_bot.reddit_gems import _thumb_of, _video_of


def test_thumb_of_none_thumbnail_no_crash():
    assert _thumb_of({"thumbnail": None}) == ""
    assert _thumb_of({"thumbnail": "default"}) == ""      # http değil → boş
    assert _thumb_of({"thumbnail": "https://x/y.jpg"}) == "https://x/y.jpg"


def test_thumb_of_prefers_preview_image():
    post = {"preview": {"images": [{"source": {"url": "https://p/img.jpg"}}]},
            "thumbnail": None}
    assert _thumb_of(post) == "https://p/img.jpg"


def test_video_of_none_url_no_crash():
    # Native olmayan post: url None → .endswith çökmemeli → None döner.
    assert _video_of({"url": None, "domain": None}) is None


def test_video_of_reddit_fallback():
    post = {"media": {"reddit_video": {
        "fallback_url": "https://v.redd.it/x/DASH.mp4?source=fallback",
        "duration": 20, "width": 1080, "height": 1920}}}
    url, dur, w, h = _video_of(post)
    assert url == "https://v.redd.it/x/DASH.mp4"           # query stripped
    assert dur == 20 and w == 1080 and h == 1920


def _vpost(sub, ups, over18=False, dur=20):
    return {"data": {"subreddit": sub, "ups": ups, "over_18": over18,
                     "num_comments": 5, "title": f"{sub} clip", "permalink": f"/r/{sub}/x",
                     "media": {"reddit_video": {
                         "fallback_url": f"https://v.redd.it/{sub}/DASH.mp4",
                         "duration": dur, "width": 1080, "height": 1920}}}}


class _Resp:
    def __init__(self, posts, after=None):
        self._posts = posts
        self._after = after
    def raise_for_status(self): pass
    def json(self):
        return {"data": {"children": self._posts, "after": self._after}}


def test_search_gems_global_filters(monkeypatch):
    """search_gems: GLOBAL /search sonuçlarını SFW + video + min_ups filtreler."""
    import short_bot.reddit_gems as g
    captured = {}

    def _fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        # restrict_sr çağrısında boş dön (yalnız global tarama sınanıyor)
        if "restrict_sr" in (params or {}):
            return _Resp([], after=None)
        return _Resp([
            _vpost("Unexpected", 5000),                 # geçer
            _vpost("nsfwsub", 9000, over18=True),       # over_18 → elenir
            _vpost("aww", 100),                         # min_ups<300 → elenir
            {"data": {"subreddit": "pics", "ups": 8000, "over_18": False,
                      "url": "https://i.imgur.com/x.jpg", "title": "resim",
                      "permalink": "/r/pics/y"}},        # video değil → elenir
        ], after=None)

    monkeypatch.setattr(g, "get_token", lambda *a, **k: "tok")
    monkeypatch.setattr(g.requests, "get", _fake_get)
    gems = g.search_gems("id", "sec", "köpek kurtarma", t="month", min_ups=300)

    assert captured["params"]["q"] == "köpek kurtarma"
    assert captured["params"]["include_over_18"] == "off"   # SFW zorlanıyor
    assert captured["params"]["t"] == "month"
    # Yalnız SFW + video + ups>=300 olan kaldı
    assert len(gems) == 1
    assert gems[0]["sub"] == "Unexpected" and gems[0]["ups"] == 5000
    assert gems[0]["video_url"] == "https://v.redd.it/Unexpected/DASH.mp4"


def test_search_gems_paginates_and_sub_restricts(monkeypatch):
    """SAYFALAMA (after) + SUB-KISITLI ikinci tarama → daha çok video (dedup'lu)."""
    import short_bot.reddit_gems as g
    calls = []

    def _fake_get(url, params=None, headers=None, timeout=None):
        params = params or {}
        calls.append((url, params))
        restricted = "restrict_sr" in params
        after = params.get("after")
        if not restricted and after is None:            # global sayfa 1 → after ver
            return _Resp([_vpost("Unexpected", 5000)], after="t3_p2")
        if not restricted and after == "t3_p2":         # global sayfa 2 → dur
            return _Resp([_vpost("funny", 4000)], after=None)
        if restricted:                                  # sub-kısıtlı → 3. video
            return _Resp([_vpost("aww", 3000)], after=None)
        return _Resp([], after=None)

    monkeypatch.setattr(g, "get_token", lambda *a, **k: "tok")
    monkeypatch.setattr(g.requests, "get", _fake_get)
    gems = g.search_gems("id", "sec", "dog", pages=3, min_ups=300)

    subs = {x["sub"] for x in gems}
    assert subs == {"Unexpected", "funny", "aww"}          # 3 kaynaktan toplandı
    assert any("restrict_sr" in p for _, p in calls)       # sub-kısıtlı tarama yapıldı
    assert all(p.get("include_over_18") == "off" for _, p in calls)  # SFW zorlanıyor
    # global 2 sayfa + en az 1 sub-kısıtlı çağrı
    assert len(calls) >= 3


def test_search_gems_empty_query():
    from short_bot.reddit_gems import search_gems
    assert search_gems("id", "sec", "   ") == []            # boş query → boş liste


def test_fetch_popular_filters(monkeypatch):
    """fetch_popular: r/popular/hot (geo GLOBAL) → SFW + video + min_ups filtreler."""
    import short_bot.reddit_gems as g
    captured = {}

    def _fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp([
            _vpost("MadeMeSmile", 5000),                # geçer
            _vpost("nsfwsub", 9000, over18=True),       # over_18 → elenir
            _vpost("aww", 100),                         # min_ups<500 → elenir
            {"data": {"subreddit": "pics", "ups": 8000, "over_18": False,
                      "url": "https://i.imgur.com/x.jpg", "title": "resim",
                      "permalink": "/r/pics/y"}},        # video değil → elenir
        ], after=None)

    monkeypatch.setattr(g, "get_token", lambda *a, **k: "tok")
    monkeypatch.setattr(g.requests, "get", _fake_get)
    gems = g.fetch_popular("id", "sec", min_ups=500)

    assert "/r/popular/hot" in captured["url"]
    assert captured["params"]["geo_filter"] == "GLOBAL"
    assert len(gems) == 1 and gems[0]["sub"] == "MadeMeSmile"


def test_reddit_pacing_and_backoff():
    """AKILLI Reddit pacing: 429'da Retry-After/Reset kadar bekle-tekrar; proaktif olarak
    kalan-kota header'ına göre yavaşla (bolsa minimum). Sabit uyku yerine header-tabanlı."""
    from short_bot.reddit_gems import _proactive_pace_s, _rate_wait_s

    class R:
        def __init__(self, h):
            self.headers = h

    # 429 backoff: Retry-After öncelikli, [1,30]'a sıkışır
    assert _rate_wait_s(R({"Retry-After": "12"})) == 12.0
    assert _rate_wait_s(R({"X-Ratelimit-Reset": "50"})) == 30.0     # capped
    assert _rate_wait_s(R({})) == 5.0                               # default
    # proaktif pacing: kota az → reset'e doğru bekle; bol → minimum 0.3
    assert _proactive_pace_s(R({"X-Ratelimit-Remaining": "1", "X-Ratelimit-Reset": "8"})) == 8.0
    assert _proactive_pace_s(R({"X-Ratelimit-Remaining": "50", "X-Ratelimit-Reset": "60"})) == 0.3


def test_find_gems_window_rotation(monkeypatch):
    """Pencere rotasyonu: /top her t_windows penceresi için çağrılır, /hot bir kez (t'siz)."""
    import short_bot.reddit_gems as rg

    calls = []
    monkeypatch.setattr(rg, "get_token", lambda *a, **k: "tok")
    monkeypatch.setattr(rg, "_fetch_listing_paged",
                        lambda sub, tok, listing, **kw: calls.append((listing, kw.get("t"))) or [])
    rg.find_gems("id", "sec", subreddits=["x"], t_windows=["month", "year"],
                 listings=("top", "hot"))
    assert ("top", "month") in calls and ("top", "year") in calls
    assert ("hot", None) in calls          # /hot t'siz (taze)
