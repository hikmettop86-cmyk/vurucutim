"""narrator.html.j2'nin __seek() davranisi — gercek tarayicida dogrulanir.

Bu testler iki gercek hatayi kalici olarak kilitler:
  1. Altyazi span'lari arasinda bosluk yoksa tarayici hepsini tek kelime sayar,
     satir kaydirmaz ve metin ekrandan tasar.
  2. hook / loop_close kendi buyuk basliklarinda gorunurken altyazinin ayni
     metni tekrar basmasi ekrani boguyordu.
"""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from short_bot.models import RenderJob, Script
from short_bot.narration import NarrationTimeline, TimedBeat, TimedWord

TPL = Path(__file__).resolve().parent.parent / "templates" / "narrator.html.j2"

WIDTH, HEIGHT = 1080, 1920


def _timeline():
    """hook(2 kelime) + beat(6 kelime) + close(2 kelime), 10 sn."""
    words = [
        TimedWord(word="Neden", start_s=0.0, end_s=0.5, seg=0),
        TimedWord(word="sasirdi", start_s=0.5, end_s=1.0, seg=0),
        # beat 0 — 6 kelime, 1.0 → 7.0
        TimedWord(word="Merkez", start_s=1.0, end_s=2.0, seg=1),
        TimedWord(word="bankasi", start_s=2.0, end_s=3.0, seg=1),
        TimedWord(word="politika", start_s=3.0, end_s=4.0, seg=1),
        TimedWord(word="faizini", start_s=4.0, end_s=5.0, seg=1),
        TimedWord(word="bes", start_s=5.0, end_s=6.0, seg=1),
        TimedWord(word="indirdi", start_s=6.0, end_s=7.0, seg=1),
        # loop_close — seg = 1 beat + 1 = 2
        TimedWord(word="Iste", start_s=7.0, end_s=8.5, seg=2),
        TimedWord(word="bu yuzden", start_s=8.5, end_s=10.0, seg=2),
    ]
    return NarrationTimeline(
        words=words,
        beats=[TimedBeat(on_screen="FAIZ INDIRIMI", start_s=1.0, end_s=7.0)],
        duration_s=10.0,
        hook="Neden sasirdi?",
        loop_close="Iste bu yuzden.",
    )


def _html():
    job = RenderJob(
        script=Script(header_top="FAIZ", header_bottom="MERKEZ BANKASI",
                      photo_overlay="BES PUAN",
                      body_paragraph="Merkez bankasi faizi bes puan indirdi bugun.",
                      highlights=[], category="Ekonomi", mood="breaking"),
        bg_image_path=None, music_path=Path("m.mp3"),
        channel_colors={"primary": "#0ea5e9", "accent": "#facc15",
                        "bg_gradient": ["#0f172a", "#020617"]},
        handle="@test", duration_s=11, narration=_timeline(),
    )
    from short_bot.renderer import build_html
    return build_html(job, TPL)


@pytest.fixture(scope="module")
def browser():
    """Tek bir sync_playwright baglami. Ic ice sync_playwright acmak
    'Please use the Async API instead' hatasi verir — bu yuzden tum
    testler bu tarayiciyi paylasir."""
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def page(browser):
    pg = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                          device_scale_factor=1)
    pg.set_content(_html(), wait_until="networkidle")
    yield pg
    pg.close()


def _seek(page, seconds: float):
    page.evaluate("(t) => window.__seek(t)", int(seconds * 1000))


def _visible_words(page) -> list[str]:
    return page.eval_on_selector_all(
        ".caption .w.vis", "els => els.map(e => e.textContent.trim())")


def _hot_words(page) -> list[str]:
    return page.eval_on_selector_all(
        ".caption .w.hot", "els => els.map(e => e.textContent.trim())")


def test_caption_never_overflows_horizontally(page):
    """Regresyon kalkani: span'lar bitisik yazilirsa satir kaymaz, metin tasar."""
    _seek(page, 3.0)
    overflow = page.eval_on_selector(
        ".caption", "el => el.scrollWidth - el.clientWidth")
    assert overflow <= 1, f"altyazi yatayda {overflow}px tasiyor"


def test_long_words_wrap_instead_of_overflowing(browser):
    """Uc UZUN kelime tek satira sigmaz; span'lar arasi bosluk yoksa
    tarayici hepsini tek token sayip 690px+ tasirir. Bu testin kalkani
    kisa kelimelerle tetiklenmez — bu yuzden ozellikle uzun kelime kullanir."""
    long_words = ["Ekonomistlere", "desteklemeyi", "ongormemisti"]
    words = [TimedWord(word="Neden", start_s=0.0, end_s=0.5, seg=0)]
    for i, w in enumerate(long_words):
        words.append(TimedWord(word=w, start_s=1.0 + i, end_s=2.0 + i, seg=1))
    words.append(TimedWord(word="Iste", start_s=5.0, end_s=6.0, seg=2))
    tl = NarrationTimeline(
        words=words, beats=[TimedBeat(on_screen="X", start_s=1.0, end_s=4.0)],
        duration_s=6.0, hook="Neden?", loop_close="Iste.",
    )
    job = RenderJob(
        script=Script(header_top="A", header_bottom="B", photo_overlay="C",
                      body_paragraph="Yeterince uzun bir govde cumlesi burada duruyor.",
                      highlights=[], category="X", mood="neutral"),
        bg_image_path=None, music_path=Path("m.mp3"),
        channel_colors={"primary": "#0ea5e9", "accent": "#facc15",
                        "bg_gradient": ["#0f172a", "#020617"]},
        handle="@t", duration_s=7, narration=tl,
    )
    from short_bot.renderer import build_html
    html = build_html(job, TPL)

    pg = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
    try:
        pg.set_content(html, wait_until="networkidle")
        pg.evaluate("(t) => window.__seek(t)", 2500)
        overflow = pg.eval_on_selector(
            ".caption", "el => el.scrollWidth - el.clientWidth")
        visible = pg.eval_on_selector_all(
            ".caption .w.vis", "els => els.map(e => e.textContent.trim())")
    finally:
        pg.close()

    assert visible == long_words
    assert overflow <= 1, f"uzun kelimeler yatayda {overflow}px tasiyor"


def test_hook_shows_big_title_and_no_caption(page):
    _seek(page, 0.4)
    assert page.eval_on_selector("#__hook", "el => el.classList.contains('on')")
    assert _visible_words(page) == [], "hook sirasinda altyazi metni tekrar ediyor"


def test_loop_close_shows_big_title_and_no_caption(page):
    _seek(page, 9.0)
    assert page.eval_on_selector("#__close", "el => el.classList.contains('on')")
    assert _visible_words(page) == [], "kapanista altyazi metni tekrar ediyor"
    assert not page.eval_on_selector("#__hook", "el => el.classList.contains('on')")


def test_beat_shows_rolling_window_of_at_most_three_words(page):
    _seek(page, 3.0)
    vis = _visible_words(page)
    assert 0 < len(vis) <= 3, f"pencere {len(vis)} kelime gosteriyor"
    assert vis == ["Merkez", "bankasi", "politika"]


def test_window_advances_to_next_chunk(page):
    _seek(page, 5.5)
    assert _visible_words(page) == ["faizini", "bes", "indirdi"]


def test_exactly_one_word_is_highlighted_during_beat(page):
    _seek(page, 3.2)
    assert _hot_words(page) == ["politika"]


def test_highlight_leads_the_voice_by_lead_ms(page):
    """Kelime soylenmeden ~80 ms once yanar."""
    _seek(page, 3.95)          # "faizini" 4.0'da basliyor
    assert "faizini" in _hot_words(page)


def test_chunk_never_spans_two_segments(page):
    """Pencere segment sinirini asmamali; iki farkli cumle ayni anda gorunmez."""
    _seek(page, 1.2)           # beat'in ilk kelimesi
    vis = _visible_words(page)
    assert "sasirdi" not in vis          # hook kelimesi sizmamali
    assert vis[0] == "Merkez"


def test_progress_bar_fills_over_time(page):
    _seek(page, 0.0)
    start = page.eval_on_selector("#__progress", "el => el.style.width")
    _seek(page, 10.0)
    end = page.eval_on_selector("#__progress", "el => el.style.width")
    assert start.startswith("0")
    assert end == "100%"


def test_beat_card_visible_only_within_its_window(page):
    _seek(page, 0.5)
    assert not page.eval_on_selector(".card", "el => el.classList.contains('on')")
    _seek(page, 3.0)
    assert page.eval_on_selector(".card", "el => el.classList.contains('on')")
    _seek(page, 8.0)
    assert not page.eval_on_selector(".card", "el => el.classList.contains('on')")
