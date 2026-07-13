import pytest

from short_bot.config import ReelConfig
from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html, _FONT_IMPORTS


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


def test_reel_font_default_and_literal():
    assert ReelConfig(enabled=True, voice_id="x").font == "Montserrat"
    with pytest.raises(Exception):
        ReelConfig(enabled=True, voice_id="x", font="ComicSans")


def test_font_imports_cover_all():
    for f in ("Montserrat", "Anton", "Bebas Neue", "Oswald", "Poppins", "Inter", "Archivo Black"):
        assert f in _FONT_IMPORTS


def test_overlay_uses_font():
    html = build_reel_overlay_html(_tl(), font="Anton")
    assert "'Anton'" in html
    assert _FONT_IMPORTS["Anton"] in html
