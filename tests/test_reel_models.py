import pytest
from pydantic import ValidationError

from short_bot.reel_models import (ReelBeat, ReelNarration, ReelTimeline,
                                   TimedWord)


def _narr(**kw):
    base = dict(
        hook="Bir kaşık bal için arılar ne yapıyor biliyor musun?",
        beats=[
            ReelBeat(text="İşçi arılar çiçekten nektar toplar.",
                     visual_query="bee on flower macro", keyword="NEKTAR TOPLAR"),
            ReelBeat(text="Nektarı midelerinde enzimlerle işler.",
                     visual_query="honey bee closeup", keyword="MİDEDE İŞLENİR"),
            ReelBeat(text="Kovanda peteğe biriktirir.",
                     visual_query="honeycomb bees", keyword="PETEĞE DOLAR"),
        ],
        close="Yani bir kaşık bal binlerce arının emeği.",
        mood="upbeat",
    )
    base.update(kw)
    return ReelNarration(**base)


def test_segments_order_and_queries():
    n = _narr()
    assert n.segments()[0] == n.hook
    assert n.segments()[-1] == n.close
    assert len(n.segments()) == 5           # hook + 3 beat + close
    # görsel sorgular: hook/close için None, beat'ler için query
    assert n.segment_queries()[0] is None
    assert n.segment_queries()[1] == "bee on flower macro"
    assert n.segment_queries()[-1] is None


def test_full_text_and_word_count():
    n = _narr()
    assert n.full_text() == " ".join(n.segments())
    assert n.word_count() == len(n.full_text().split())


def test_beats_min_three():
    with pytest.raises(ValidationError):
        _narr(beats=[ReelBeat(text="Tek beat cümlesi burada.",
                              visual_query="xy", keyword="X")])


def test_beats_max_six():
    b = ReelBeat(text="Bir beat cümlesi.", visual_query="xy", keyword="X")
    with pytest.raises(ValidationError):
        _narr(beats=[b] * 7)


def test_visual_query_required_nonempty():
    with pytest.raises(ValidationError):
        ReelBeat(text="Cümle burada yeterince uzun.", visual_query="  ", keyword="X")


def test_turkish_preserved():
    n = _narr()
    assert "İşçi" in n.beats[0].text and "çiçekten" in n.beats[0].text


def test_timeline_holds_words_and_beats():
    tl = ReelTimeline(
        words=[TimedWord(word="Bir", start_s=0.0, end_s=0.2, seg=0)],
        seg_spans=[(0.0, 1.0), (1.0, 3.0)],
        seg_queries=[None, "bee on flower macro"],
        seg_keywords=["", "NEKTAR TOPLAR"],
        duration_s=12.0, hook="Bir?", close="Son.",
    )
    assert tl.duration_s == 12.0
    assert tl.seg_queries[1] == "bee on flower macro"
