import pytest
from playwright.sync_api import sync_playwright

from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html

W, H = 1080, 1920


def _tl():
    n = ReelNarration(
        hook="Bal nasıl olur?",
        beats=[ReelBeat(text="Arılar nektar toplar burada.", visual_query="bee flower", keyword="NEKTAR"),
               ReelBeat(text="Enzimlerle işler bunu.", visual_query="bee macro", keyword="ENZİM"),
               ReelBeat(text="Peteğe biriktirir hemen.", visual_query="honeycomb", keyword="PETEK")],
        close="İşte arının emeği.", mood="upbeat")
    asr = [TimedWord(word=f"w{i}", start_s=float(i), end_s=float(i+1), seg=-1)
           for i in range(n.word_count())]
    return build_reel_timeline(n, asr, duration_s=float(n.word_count()))


def test_no_cta_when_empty():
    html = build_reel_overlay_html(_tl(), cta_text="", handle="@t")
    assert 'id="cta"' not in html


def test_cta_element_present():
    html = build_reel_overlay_html(_tl(), cta_text="ABONE OL", handle="@t")
    assert 'id="cta"' in html and "ABONE OL" in html


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(); yield b; b.close()


def test_cta_shows_only_at_end(browser):
    html = build_reel_overlay_html(_tl(), cta_text="ABONE OL", handle="@t")
    pg = browser.new_page(viewport={"width": W, "height": H})
    try:
        pg.set_content(html, wait_until="networkidle")
        dur = _tl().duration_s
        pg.evaluate("(t)=>window.__seek(t)", 500)             # başta
        assert not pg.eval_on_selector("#cta", "e=>e.classList.contains('on')")
        pg.evaluate("(t)=>window.__seek(t)", int((dur - 0.5) * 1000))  # sonda
        assert pg.eval_on_selector("#cta", "e=>e.classList.contains('on')")
    finally:
        pg.close()
