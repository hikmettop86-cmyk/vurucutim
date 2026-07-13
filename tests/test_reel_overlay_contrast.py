from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html


def _tl():
    n = ReelNarration(
        hook="Bal nasıl olur?",
        beats=[ReelBeat(text="Arılar nektar toplar burada.", visual_query="bee flower", keyword="NEKTAR"),
               ReelBeat(text="Enzimlerle işler bunu.", visual_query="bee macro", keyword="ENZİM"),
               ReelBeat(text="Peteğe biriktirir hemen.", visual_query="honeycomb", keyword="PETEK")],
        close="İşte arının emeği.", mood="upbeat")
    # ASR kelimeleri anlatımın KENDİ kelimeleri: çizelge artık eşleştirmeyle
    # hizalıyor, uydurma "w0/w1" oransal yedeğe düşer (üretim yolunu sınamaz).
    asr = [TimedWord(word=w, start_s=float(i), end_s=float(i+1), seg=-1)
           for i, w in enumerate(n.full_text().split())]
    return build_reel_timeline(n, asr, duration_s=float(n.word_count()))


def test_dark_highlight_readable():
    html = build_reel_overlay_html(_tl(), highlight_color="#0a2540")
    # kutu yazısı beyaz (koyu zemin)
    assert "#ffffff" in html
    # hot kelime kuralı hâlâ mevcut (parlaklaştırılmış renk atanmış)
    assert ".w.hot" in html


def test_light_highlight_dark_chip_text():
    html = build_reel_overlay_html(_tl(), highlight_color="#ffd400")
    assert "#111111" in html
