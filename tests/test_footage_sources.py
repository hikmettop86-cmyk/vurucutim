from pathlib import Path
from short_bot.footage_sources import (FootageCandidate, PexelsSource,
                                       PixabaySource)


def test_pixabay_parses(monkeypatch):
    def fake_get(url, timeout=None, **k):
        class R:
            status_code = 200
            def json(self):
                return {"hits": [{"id": 7, "duration": 12,
                    "videos": {"large": {"url": "http://v/large.mp4", "width": 1920,
                                         "height": 1080, "thumbnail": "http://t.jpg"}}}]}
        return R()
    import short_bot.footage_sources as fs
    monkeypatch.setattr(fs.requests, "get", fake_get)
    src = PixabaySource(api_key="k")
    # fixture yatay (1920x1080) → landscape pass'te geçer
    cands = src.search("kedi", max_results=15, orientation="landscape")
    assert len(cands) == 1
    assert cands[0].url == "http://v/large.mp4"
    assert cands[0].duration_s == 12
    assert cands[0].image == "http://t.jpg"
    assert cands[0].source == "pixabay" and cands[0].ident == "7"


def test_pixabay_portrait_filters_landscape(monkeypatch):
    def fake_get(url, timeout=None, **k):
        class R:
            status_code = 200
            def json(self):
                return {"hits": [
                    {"id": 1, "duration": 9, "videos": {"large": {"url": "l.mp4", "width": 1920, "height": 1080, "thumbnail": "t"}}},
                    {"id": 2, "duration": 9, "videos": {"large": {"url": "p.mp4", "width": 1080, "height": 1920, "thumbnail": "t"}}},
                    {"id": 3, "duration": 9, "videos": {"large": {"url": "s.mp4", "width": 1080, "height": 1080, "thumbnail": "t"}}},
                ]}
        return R()
    import short_bot.footage_sources as fs
    monkeypatch.setattr(fs.requests, "get", fake_get)
    src = PixabaySource(api_key="k")
    port = src.search("x", max_results=15, orientation="portrait")
    assert [c.ident for c in port] == ["2", "3"]      # yatay (1) atlandı, dikey+kare kaldı
    assert len(src.search("x", max_results=15, orientation="landscape")) == 3  # yedek: hepsi


def test_pixabay_empty_and_unavailable(monkeypatch):
    import short_bot.footage_sources as fs
    monkeypatch.setattr(fs.requests, "get",
                        lambda *a, **k: type("R", (), {"status_code": 200,
                        "json": lambda s: {"hits": []}})())
    assert PixabaySource(api_key="k").search("x", max_results=5, orientation="portrait") == []
    assert PixabaySource(api_key="").available() is False


def test_pexels_source_wraps(monkeypatch):
    import short_bot.footage_sources as fs
    from short_bot.pexels import PexelsCandidate
    monkeypatch.setattr(fs, "_pexels_search",
        lambda q, key, **k: [PexelsCandidate(id=1, url="http://p.mp4", duration_s=8, image="http://pi.jpg")])
    src = PexelsSource(api_key="k")
    cands = src.search("x", max_results=5, orientation="portrait")
    assert cands[0].url == "http://p.mp4" and cands[0].source == "pexels"
    assert PexelsSource(api_key="").available() is False


def test_build_footage_sources_priority_and_gating():
    from short_bot.footage_sources import build_footage_sources
    # her iki anahtar var → öncelik sırası korunur
    srcs = build_footage_sources(["pixabay", "pexels"], pexels_key="p", pixabay_key="x")
    assert [s.name for s in srcs] == ["pixabay", "pexels"]
    # sadece pexels anahtarı → pixabay/storyblocks elenir
    srcs = build_footage_sources(["storyblocks", "pixabay", "pexels"],
                                 pexels_key="p", pixabay_key="")
    assert [s.name for s in srcs] == ["pexels"]


def test_build_footage_sources_fallback():
    from short_bot.footage_sources import build_footage_sources
    # boş öncelik → pexels fallback
    assert [s.name for s in build_footage_sources([], pexels_key="p")] == ["pexels"]
    # hepsi kullanılamaz (anahtar yok) → yine [PexelsSource] fallback (tek eleman)
    out = build_footage_sources(["pixabay"], pexels_key="", pixabay_key="")
    assert len(out) == 1 and out[0].name == "pexels"
