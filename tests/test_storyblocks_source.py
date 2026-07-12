"""Storyblocks tarayıcı-oturum kaynağı testleri.

TÜM Playwright etkileşimleri MONKEYPATCH'lenir — gerçek tarayıcı AÇILMAZ.
`_scrape_page` / `_member_download` örnek üstünde sahtelenir; testler yalnız saf
mantığı (query sadeleştirme, oturum kontrolü, kart eşleme, filigran-boyut reddi)
sınar.
"""
from short_bot.storyblocks_source import (StoryblocksSource, _EXTRACT_JS,
                                          _simplify_query)


def test_extract_js_reads_video_poster_thumbnail():
    """Storyblocks kartı <img> değil <video poster>: kazıma poster'ı okumalı.

    Gerçek hata (2026-07-12): thumbnail boş kalınca alaka kapısı indirmeden ÖNCE
    çalışamıyordu → her aday TARAYICIYLA indiriliyordu (üretim yavaşlığının ana
    kaynağı). Bu test poster fallback zincirini kilitler."""
    assert "poster" in _EXTRACT_JS
    assert "querySelector('video')" in _EXTRACT_JS
    assert "data-src" in _EXTRACT_JS and "srcset" in _EXTRACT_JS


def test_simplify_query_strips_stopwords():
    q = _simplify_query("the amazing story of a blue whale video footage")
    assert "video" not in q and "footage" not in q and "story" not in q
    assert "whale" in q and len(q.split()) <= 5


def test_available_needs_session(tmp_path):
    assert StoryblocksSource(session_path=tmp_path / "yok.json").available() is False
    sess = tmp_path / "s.json"
    sess.write_text("x" * 100)
    assert StoryblocksSource(session_path=sess).available() is True


def test_search_scrapes_cards(tmp_path, monkeypatch):
    sess = tmp_path / "s.json"
    sess.write_text("x" * 100)
    src = StoryblocksSource(session_path=sess)
    # _scrape_page'i sahtele (tarayıcı çağrısı yerine kart listesi döndür)
    monkeypatch.setattr(
        src, "_scrape_page",
        lambda url, deadline=None: [{
            "id": "111",
            "href": "https://www.storyblocks.com/video/stock/whale-111",
            "thumb": "t.jpg",
            "title": "blue whale",
        }])
    cands = src.search("blue whale", max_results=15, orientation="portrait")
    assert cands and cands[0].source == "storyblocks"
    assert "storyblocks.com/video/stock" in cands[0].url and cands[0].ident == "111"


def test_download_rejects_watermark(tmp_path, monkeypatch):
    sess = tmp_path / "s.json"
    sess.write_text("x" * 100)
    src = StoryblocksSource(session_path=sess)
    from short_bot.footage_sources import FootageCandidate

    # _member_download sahtesi: küçük (filigranlı) dosya yazar
    def fake_dl(detail_url, out):
        out.write_bytes(b"x" * 1000)
        return out   # <1.5MB → filigran

    monkeypatch.setattr(src, "_member_download", fake_dl)
    cand = FootageCandidate(
        url="https://www.storyblocks.com/video/stock/x-1", source="storyblocks")
    assert src.download(cand, tmp_path) is None   # filigran reddi


def test_storyblocks_close_idempotent_when_not_started():
    """close() hiç başlamamışken güvenli (no-op) — reel.py her render öncesi çağırır."""
    from short_bot.storyblocks_browser import close
    close()
    close()  # çift çağrı da patlamaz


def test_reel_imports_storyblocks_close():
    """reel.py, render öncesi storyblocks close'u çağırabilmeli (import edilebilir)."""
    from short_bot.storyblocks_browser import close  # noqa: F401
    import short_bot.reel  # noqa: F401 — import hatasi olmamali
