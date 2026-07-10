from pathlib import Path

from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html


def _tl():
    n = ReelNarration(
        hook="Bal nasıl olur?",
        beats=[ReelBeat(text="Arılar nektar toplar burada.", visual_query="bee flower", keyword="NEKTAR"),
               ReelBeat(text="Enzimlerle işler.", visual_query="bee macro", keyword="ENZİM"),
               ReelBeat(text="Peteğe biriktirir hemen.", visual_query="honeycomb", keyword="PETEK")],
        close="İşte arının emeği.", mood="upbeat")
    asr = [TimedWord(word=f"w{i}", start_s=float(i), end_s=float(i+1), seg=-1)
           for i in range(n.word_count())]
    return build_reel_timeline(n, asr, duration_s=float(n.word_count()))


def test_layout_class_in_body():
    for layout in ("classic", "lower_left", "top_heavy"):
        html = build_reel_overlay_html(_tl(), layout=layout, handle="@t")
        assert f'class="stage {layout}"' in html or f"layout-{layout}" in html


def test_unknown_layout_falls_back_classic():
    html = build_reel_overlay_html(_tl(), layout="bogus", handle="@t")
    assert "classic" in html


def test_default_layout_is_classic():
    html = build_reel_overlay_html(_tl(), handle="@t")
    assert "classic" in html
