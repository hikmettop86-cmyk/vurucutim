import pytest

from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)


def _narr():
    return ReelNarration(
        hook="Bal nasıl olur?",                       # 3 kelime
        beats=[
            ReelBeat(text="Arılar nektar toplar burada.", visual_query="bee flower", keyword="NEKTAR"),  # 4
            ReelBeat(text="Enzimlerle işler.", visual_query="bee macro", keyword="ENZİM"),               # 2
            ReelBeat(text="Peteğe biriktirir hemen.", visual_query="honeycomb", keyword="PETEK"),        # 3
        ],
        close="İşte arının emeği.", mood="upbeat",     # 3
    )  # toplam 15 kelime


def _asr(n):
    return [TimedWord(word=f"w{i}", start_s=float(i), end_s=float(i+1), seg=-1) for i in range(n)]


def test_asr_match_uses_asr_times_but_narration_words():
    n = _narr(); tot = n.word_count()
    tl = build_reel_timeline(n, _asr(tot), duration_s=float(tot))
    assert len(tl.words) == tot
    assert tl.words[0].word == "Bal"            # anlatım metni, ASR değil
    assert tl.words[-1].end_s == pytest.approx(float(tot))
    assert tl.seg_queries == [None, "bee flower", "bee macro", "honeycomb", None]
    assert tl.seg_keywords == ["", "NEKTAR", "ENZİM", "PETEK", ""]


def test_seg_spans_cover_full_duration():
    n = _narr()
    tl = build_reel_timeline(n, _asr(n.word_count()), duration_s=15.0)
    assert len(tl.seg_spans) == 5             # hook + 3 beat + close
    assert tl.seg_spans[0][0] == 0.0
    assert tl.seg_spans[-1][1] == pytest.approx(15.0)
    # bitişik, boşluksuz
    for (a, b), (c, d) in zip(tl.seg_spans, tl.seg_spans[1:]):
        assert b == pytest.approx(c)


def test_proportional_fallback_on_mismatch():
    n = _narr()
    tl = build_reel_timeline(n, _asr(5), duration_s=20.0)
    assert len(tl.words) == n.word_count()
    assert tl.words[-1].end_s == pytest.approx(20.0)
    for a, b in zip(tl.words, tl.words[1:]):
        assert a.end_s <= b.start_s + 1e-9 and a.start_s < a.end_s


def test_empty_asr_uses_proportional():
    n = _narr()
    tl = build_reel_timeline(n, [], duration_s=12.0)
    assert len(tl.words) == n.word_count()
    assert tl.duration_s == 12.0


def test_rejects_nonpositive_duration():
    with pytest.raises(ValueError, match="duration_s"):
        build_reel_timeline(_narr(), [], duration_s=0.0)
