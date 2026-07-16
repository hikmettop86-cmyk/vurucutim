"""Açık soru çipi: hook'un açtığı merak sorusu ekranda asılı kalır,
reveal anında 'cevaplandı'ya döner (merak mimarisi, spec 2026-07-16)."""
from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html


def _tl():
    n = ReelNarration(
        hook="Bu tip neden herkesi korkutuyor?",
        beats=[ReelBeat(text="Beat bir cumlesi burada", visual_query="q0", keyword="A"),
               ReelBeat(text="Beat iki cumlesi burada", visual_query="q1", keyword="B"),
               ReelBeat(text="Beat uc cumlesi burada", visual_query="q2", keyword="C")],
        close="Kapanis cumlesi korkutuyor iste", mood="upbeat")
    words = n.full_text().split()
    asr = [TimedWord(word=w, start_s=i * .4, end_s=i * .4 + .35, seg=-1)
           for i, w in enumerate(words)]
    return build_reel_timeline(n, asr, duration_s=len(words) * .4)


def test_soru_verilince_cip_render_edilir():
    html = build_reel_overlay_html(_tl(), question_text="Neden herkes korkuyor?",
                                   reveal_at_s=12.0)
    assert 'id="qchip"' in html
    assert "Neden herkes korkuyor?" in html
    assert "QREVEAL=12.000" in html


def test_soru_yoksa_cip_DOM_da_yok():
    html = build_reel_overlay_html(_tl())
    assert 'id="qchip"' not in html


def test_cip_kare_dedup_imzasina_dahil():
    html = build_reel_overlay_html(_tl(), question_text="Soru bu mu?",
                                   reveal_at_s=8.0)
    i = html.index("window.__sig")
    assert "QCHIP" in html[i:]        # imza çipin durumunu içeriyor


def test_soru_48_karaktere_kirpilir():
    html = build_reel_overlay_html(_tl(), question_text="X" * 200, reveal_at_s=5.0)
    # render katmanı da kırpar (şema kırpması + savunma derinliği)
    i = html.index('id="qchip"')
    blok = html[i:i + 200]
    assert "X" * 49 not in blok
