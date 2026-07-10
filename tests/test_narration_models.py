import pytest
from pydantic import ValidationError

from short_bot.narration import (Beat, Narration, NarrationTimeline, TimedBeat,
                                 TimedWord)


def _narration(**kw):
    base = dict(
        hook="Bu karar neden herkesi sasirtti?",
        beats=[
            Beat(text="Merkez bankasi faizi bes puan indirdi.", on_screen="FAIZ INDIRIMI"),
            Beat(text="Piyasalar bunu beklemiyordu.", on_screen="BEKLENMEYEN HAMLE"),
            Beat(text="Kur ilk saatte yuzde iki yukseldi.", on_screen="KUR YUZDE 2"),
        ],
        loop_close="Iste bu yuzden herkes sasirdi.",
        mood="breaking",
    )
    base.update(kw)
    return Narration(**base)


def test_segments_order_is_hook_beats_close():
    n = _narration()
    segs = n.segments()
    assert segs[0] == n.hook
    assert segs[1] == n.beats[0].text
    assert segs[-1] == n.loop_close
    assert len(segs) == 5  # hook + 3 beat + close


def test_full_text_joins_segments_with_space():
    n = _narration()
    assert n.full_text() == " ".join(n.segments())


def test_word_count_counts_all_segments():
    n = _narration()
    assert n.word_count() == len(n.full_text().split())


def test_beats_min_three():
    with pytest.raises(ValidationError):
        _narration(beats=[Beat(text="Tek bir beat var burada.", on_screen="X")])


def test_beats_max_five():
    b = Beat(text="Bir cumle daha yaziyoruz.", on_screen="X")
    with pytest.raises(ValidationError):
        _narration(beats=[b] * 6)


def test_on_screen_max_60_chars():
    with pytest.raises(ValidationError):
        Beat(text="Yeterince uzun bir cumle.", on_screen="x" * 61)


def test_timeline_holds_words_and_beats():
    tl = NarrationTimeline(
        words=[TimedWord(word="Bu", start_s=0.0, end_s=0.2, seg=0)],
        beats=[TimedBeat(on_screen="FAIZ", start_s=1.0, end_s=3.0)],
        duration_s=48.5, hook="Bu karar?", loop_close="Iste bu yuzden.",
    )
    assert tl.duration_s == 48.5
    assert tl.words[0].seg == 0
    assert tl.beats[0].on_screen == "FAIZ"
