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


def test_search_gems_global_filters(monkeypatch):
    """search_gems: GLOBAL /search sonuçlarını SFW + video + min_ups filtreler."""
    import short_bot.reddit_gems as g

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"data": {"children": [
                _vpost("Unexpected", 5000),                 # geçer
                _vpost("nsfwsub", 9000, over18=True),       # over_18 → elenir
                _vpost("aww", 100),                         # min_ups<300 → elenir
                {"data": {"subreddit": "pics", "ups": 8000, "over_18": False,
                          "url": "https://i.imgur.com/x.jpg", "title": "resim",
                          "permalink": "/r/pics/y"}},        # video değil → elenir
            ]}}

    captured = {}

    def _fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp()

    monkeypatch.setattr(g, "get_token", lambda *a, **k: "tok")
    monkeypatch.setattr(g.requests, "get", _fake_get)
    gems = g.search_gems("id", "sec", "köpek kurtarma", t="month", min_ups=300)

    assert captured["url"].endswith("/search")
    assert captured["params"]["q"] == "köpek kurtarma"
    assert captured["params"]["include_over_18"] == "off"   # SFW zorlanıyor
    assert captured["params"]["t"] == "month"
    # Yalnız SFW + video + ups>=300 olan kaldı
    assert len(gems) == 1
    assert gems[0]["sub"] == "Unexpected" and gems[0]["ups"] == 5000
    assert gems[0]["video_url"] == "https://v.redd.it/Unexpected/DASH.mp4"


def test_search_gems_empty_query():
    from short_bot.reddit_gems import search_gems
    assert search_gems("id", "sec", "   ") == []            # boş query → boş liste
