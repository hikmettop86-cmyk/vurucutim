import pytest

from short_bot.narration import Beat, Narration, TimedWord
from short_bot.tts.align import build_timeline, transcribe_words


def _narration():
    return Narration(
        hook="Neden herkes sasirdi?",                     # 3 kelime
        beats=[
            Beat(text="Faiz bes puan indi.", on_screen="FAIZ"),        # 4
            Beat(text="Piyasalar beklemiyordu bunu.", on_screen="SURPRIZ"),  # 3
            Beat(text="Kur hemen yukseldi.", on_screen="KUR"),         # 3
        ],
        loop_close="Iste tam bu yuzden.",                 # 4
        mood="breaking",
    )
    # toplam 17 kelime


def _asr_words(n, step=1.0):
    """ASR kelimeleri anlatimin KENDI kelimeleri: cizelge artik SAYI esitligine
    degil ESLESTIRMEYE dayaniyor (whisper senaryoyla ayni kelimelere bolmez).
    Uydurma "w0/w1" hicbir seye eslesmez ve orantili yedege duserdi."""
    words = _narration().full_text().split()
    return [TimedWord(word=words[i] if i < len(words) else f"x{i}",
                      start_s=i * step, end_s=(i + 1) * step, seg=-1)
            for i in range(n)]


def test_timeline_uses_asr_timings_when_counts_match():
    n = _narration()
    total = n.word_count()
    tl = build_timeline(n, _asr_words(total), duration_s=float(total))

    assert len(tl.words) == total
    assert tl.words[0].word == "Neden"          # anlatim metni kullanilir, ASR degil
    assert tl.words[0].start_s == 0.0
    assert tl.words[-1].end_s == pytest.approx(float(total))
    assert tl.duration_s == float(total)
    assert tl.hook == n.hook and tl.loop_close == n.loop_close


def test_timeline_segments_are_indexed_hook_beats_close():
    n = _narration()
    tl = build_timeline(n, _asr_words(n.word_count()), duration_s=17.0)
    segs = [w.seg for w in tl.words]
    assert segs[:3] == [0, 0, 0]           # hook
    assert segs[3:7] == [1, 1, 1, 1]       # beat 0
    assert segs[-4:] == [4, 4, 4, 4]       # loop_close (seg = 3 beat + 1)


def test_timeline_beats_span_first_to_last_word_of_segment():
    n = _narration()
    tl = build_timeline(n, _asr_words(n.word_count()), duration_s=17.0)
    assert len(tl.beats) == 3
    assert tl.beats[0].on_screen == "FAIZ"
    # beat 0 = kelime indeksleri 3..6
    assert tl.beats[0].start_s == 3.0
    assert tl.beats[0].end_s == 7.0
    assert tl.beats[1].start_s == tl.beats[0].end_s


def test_timeline_eslesen_kelimeler_asr_zamanini_alir_sayi_tutmasa_da():
    """ASR eksik kelime cikardiysa ESLESENLER yine gercek zamanini alir.

    Eskiden sayi tutmazsa TUM hizalama atiliyordu; whisper senaryoyla ayni
    kelimelere bolmedigi icin bu neredeyse her videoda oluyordu ve altyazi sese
    hic kilitlenmiyordu (olculdu: ikinci yarida 3.2sn gecikme).
    """
    n = _narration()
    tl = build_timeline(n, _asr_words(5), duration_s=20.0)

    assert len(tl.words) == n.word_count()
    assert tl.words[0].start_s == 0.0
    assert tl.words[4].start_s == 4.0        # ASR zamani, orantili DEGIL
    assert tl.words[-1].end_s == pytest.approx(20.0)
    # monoton artan, bosluksuz
    for a, b in zip(tl.words, tl.words[1:]):
        assert a.end_s <= b.start_s + 1e-9
        assert a.start_s < a.end_s


def test_timeline_hicbiri_eslesmezse_orantiliya_duser():
    n = _narration()
    bos = [TimedWord(word=f"zzz{i}", start_s=float(i), end_s=float(i) + 0.5, seg=-1)
           for i in range(5)]
    tl = build_timeline(n, bos, duration_s=20.0)
    assert tl.words[-1].end_s == pytest.approx(20.0)


def test_timeline_falls_back_when_asr_empty():
    n = _narration()
    tl = build_timeline(n, [], duration_s=12.0)
    assert len(tl.words) == n.word_count()
    assert tl.words[-1].end_s == pytest.approx(12.0)
    assert len(tl.beats) == 3


def test_timeline_rejects_nonpositive_duration():
    with pytest.raises(ValueError, match="duration_s"):
        build_timeline(_narration(), [], duration_s=0.0)


class _FWord:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


class _FSeg:
    def __init__(self, words):
        self.words = words


def test_transcribe_words_uses_injected_backend(tmp_path):
    """faster-whisper modeli enjekte edilebilir -> torch olmadan test edilir."""
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    class FakeModel:
        def transcribe(self, audio, language=None, word_timestamps=False, **kw):
            seg = _FSeg([_FWord("bir", 0.0, 0.4), _FWord("iki", 0.4, 0.9)])
            return [seg], {"language": language}

    words = transcribe_words(audio, language="tr", _model=FakeModel())
    assert [w.word for w in words] == ["bir", "iki"]
    assert words[1].start_s == 0.4


def test_transcribe_words_skips_words_without_timestamps(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")

    class FakeModel:
        def transcribe(self, audio, language=None, word_timestamps=False, **kw):
            seg = _FSeg([
                _FWord("bir", 0.0, 0.4),
                _FWord("eksik", None, None),          # start/end yok -> atlanir
            ])
            return [seg], {"language": language}

    words = transcribe_words(audio, language="tr", _model=FakeModel())
    assert [w.word for w in words] == ["bir"]
