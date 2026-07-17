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
