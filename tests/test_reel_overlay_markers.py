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


def test_overlay_renders_markers():
    html = build_reel_overlay_html(_tl(), markers=[{"seg": 1, "type": "ring", "x": 0.3, "y": 0.4}])
    assert "#markers" in html or "markers" in html   # belirteç konteyneri var
    assert "ring" in html                            # tür JS'e geçti
    assert "0.3" in html                             # x konumu JS'e geçti


def test_overlay_no_markers_ok():
    html = build_reel_overlay_html(_tl())            # markers yoksa patlamaz
    assert "__seek" in html
