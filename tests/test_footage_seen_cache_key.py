"""Yargı önbelleği (GÖRSEL, SORGU) çiftine bağlı olmalı — sadece görsele DEĞİL.

GERÇEK HATA (short_id=748): 14 klip kabul edildi ama logda 6 vision yargısı vardı.
Sebep: önbellek anahtarı yalnız ``image_url``'di. Aynı popüler okyanus klibi farklı
sorgularda da dönüyor ve:

  "ocean low tide path" için verilen [ok] yargısı,
  "earth moon gravity pull" sorgusunda YENİDEN YARGILANMADAN kullanılıyordu.

Yani ay-yerçekimi segmentine okyanus klibi "kapıdan geçmiş" gibi giriyordu.
``matches`` alanı SORGUYA karşı verilen bir yargıdır; sorgu değişince yargı da
değişir.

Önbelleğin ASIL amacı korunuyor: AYNI sorgu için aynı adayı iki kez yargılamamak
(bir segment 3 klip isterken arama baştan taranıyor).
"""
import short_bot.footage_matcher as fm


class _R:
    status_code = 200
    content = b"jpg"


def test_same_image_different_query_is_re_judged(monkeypatch):
    """Sorgu değişince yargı YENİDEN alınmalı — okyanus klibi ay sorgusuna girmesin."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: _R())
    judged = []

    def fake_judge(path, query, *, vision_call, context=""):
        judged.append(query)
        # okyanus sorgusuna uyar, ay sorgusuna UYMAZ
        ok = "ocean" in query
        return fm._FootageVerdict(content="an ocean path", matches=ok,
                                  in_context=ok, clear=True)

    monkeypatch.setattr(fm, "_judge_image_file", fake_judge)
    seen: dict = {}
    url = "https://x/ocean.jpg"

    assert fm.verify_clip_matches(url, "ocean low tide path",
                                  vision_call=object(), seen=seen) is True
    # AYNI görsel, BAŞKA sorgu → yeniden yargılanmalı ve REDDEDİLMELİ
    assert fm.verify_clip_matches(url, "earth moon gravity pull",
                                  vision_call=object(), seen=seen) is False
    assert judged == ["ocean low tide path", "earth moon gravity pull"], (
        "sorgu değişmesine rağmen önbellekten yanıtlandı")


def test_same_image_same_query_hits_the_cache(monkeypatch):
    """Önbelleğin ASIL işi: aynı sorgu için aynı adayı iki kez yargılama."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: _R())
    judged = []

    def fake_judge(path, query, *, vision_call, context=""):
        judged.append(query)
        return fm._FootageVerdict(content="x", matches=False, in_context=False,
                                  clear=True)

    monkeypatch.setattr(fm, "_judge_image_file", fake_judge)
    seen: dict = {}
    url = "https://x/a.jpg"
    fm.verify_clip_matches(url, "kondor", vision_call=object(), seen=seen)
    fm.verify_clip_matches(url, "kondor", vision_call=object(), seen=seen)
    assert len(judged) == 1, "aynı (görsel, sorgu) iki kez yargılandı"


def test_frame_gate_cache_is_also_query_scoped(monkeypatch, tmp_path):
    """Thumbnail'sız kaynakta da (klip, sorgu) anahtarı geçerli."""
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    judged = []

    monkeypatch.setattr(fm, "_extract_cropped_frame",
                        lambda c, ff, out, at_s=1.0: out.write_bytes(b"x") or out)

    def fake_judge(path, query, *, vision_call, context=""):
        judged.append(query)
        return fm._FootageVerdict(content="x", matches=("ocean" in query),
                                  in_context=True, clear=True)

    monkeypatch.setattr(fm, "_judge_image_file", fake_judge)
    seen: dict = {}
    assert fm.verify_clip_frame_matches(clip, "ocean path",
                                        vision_call=object(), seen=seen) is True
    assert fm.verify_clip_frame_matches(clip, "moon gravity",
                                        vision_call=object(), seen=seen) is False
    assert len(judged) == 2
