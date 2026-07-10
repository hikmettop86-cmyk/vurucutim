from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html

WIDTH, HEIGHT = 1080, 1920


def _timeline():
    n = ReelNarration(
        hook="Bal nasıl olur?",
        beats=[
            ReelBeat(text="Arılar nektar toplar burada.", visual_query="bee flower", keyword="NEKTAR"),
            ReelBeat(text="Enzimlerle işler.", visual_query="bee macro", keyword="ENZİM"),
            ReelBeat(text="Peteğe biriktirir hemen.", visual_query="honeycomb", keyword="PETEK"),
        ],
        close="İşte arının emeği.", mood="upbeat",
    )
    asr = [TimedWord(word=f"w{i}", start_s=float(i), end_s=float(i+1), seg=-1)
           for i in range(n.word_count())]
    return build_reel_timeline(n, asr, duration_s=float(n.word_count()))


def _html(**kw):
    opts = dict(highlight_color="#ffd400", arrow_color="#ff2d2d",
                arrow_frequency="beats", flash=True, handle="@test")
    opts.update(kw)
    return build_reel_overlay_html(_timeline(), **opts)


def test_html_contains_turkish_and_seek():
    html = _html()
    assert "window.__seek" in html
    assert "Arılar" in html and "İşte" in html      # Türkçe korunmuş
    assert "NEKTAR" in html                          # keyword karti
    assert "#ffd400" in html                         # vurgu rengi


def test_arrow_off_frequency_hides_arrow():
    html = _html(arrow_frequency="off")
    assert "ARROWSEGS=[]" in html.replace(" ", "")


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(); yield b; b.close()


def _page(browser, html):
    pg = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
    pg.set_content(html, wait_until="networkidle"); return pg


def test_hook_shows_and_caption_hidden_at_start(browser):
    pg = _page(browser, _html())
    try:
        pg.evaluate("(t)=>window.__seek(t)", 200)
        assert pg.eval_on_selector("#hook", "e=>e.classList.contains('on')")
        vis = pg.eval_on_selector_all(".cap .w.vis", "e=>e.length")
        assert vis == 0
    finally:
        pg.close()


def test_caption_rolling_window_max_three(browser):
    pg = _page(browser, _html())
    try:
        # ikinci segmentin ortasi
        pg.evaluate("(t)=>window.__seek(t)", 4500)
        vis = pg.eval_on_selector_all(".cap .w.vis", "e=>e.map(x=>x.textContent.trim())")
        assert 0 < len(vis) <= 3
    finally:
        pg.close()


def test_flash_opacity_spikes_at_cut(browser):
    pg = _page(browser, _html())
    try:
        # ilk cut ~3.0s (hook 3 kelime = 0-3s). cut aninda flash>0
        pg.evaluate("(t)=>window.__seek(t)", 3010)
        op = pg.eval_on_selector("#flash", "e=>parseFloat(e.style.opacity||'0')")
        assert op > 0
    finally:
        pg.close()
