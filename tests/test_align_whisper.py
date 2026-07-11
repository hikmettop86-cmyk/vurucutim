from pathlib import Path

from short_bot.tts.align import transcribe_words, _resolve_whisper


class _FakeWord:
    def __init__(self, w, s, e):
        self.word, self.start, self.end = w, s, e


class _FakeSeg:
    def __init__(self, words):
        self.words = words


class _FakeModel:
    def __init__(self, *a, **k):
        pass

    def transcribe(self, audio, language=None, word_timestamps=False, **k):
        seg = _FakeSeg([_FakeWord("merhaba", 0.0, 0.4), _FakeWord("dünya", 0.4, 0.9)])
        return [seg], {"language": language}


def test_transcribe_parses_word_timestamps(tmp_path):
    words = transcribe_words(tmp_path / "a.mp3", language="tr", _model=_FakeModel())
    assert [w.word for w in words] == ["merhaba", "dünya"]
    assert words[0].start_s == 0.0 and words[1].end_s == 0.9


def test_quality_off_returns_empty(tmp_path):
    assert transcribe_words(tmp_path / "a.mp3", language="tr",
                            quality="off", _model=_FakeModel()) == []


def test_resolve_whisper_tiers():
    assert _resolve_whisper("high", "cpu")[0] == "large-v3"
    assert _resolve_whisper("low", "cpu")[0] == "base"
    ms, dev, ct = _resolve_whisper("auto", "cpu")
    assert ms == "base" and dev == "cpu" and ct == "int8"


def test_not_installed_falls_back(tmp_path, monkeypatch):
    # _model=None + faster_whisper importu yoksa [] döner
    import short_bot.tts.align as al
    monkeypatch.setattr(al, "_import_model", lambda: None)
    assert transcribe_words(tmp_path / "a.mp3", language="tr") == []
