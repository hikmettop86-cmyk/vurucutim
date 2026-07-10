import pytest

from short_bot.narration import Beat, Narration
from short_bot.narration_writer import (WORDS_PER_SECOND, build_narration_prompt,
                                        word_budget, write_narration)


class _Item:
    title = "Merkez bankasi faizi indirdi"
    link = "https://example.com/haber"
    source = "Ornek Gazete"


class _Channel:
    slug = "test-anlatici"
    language = "tr"
    handle = "@test"

    class voice:  # noqa: N801 — basit stub
        persona = "enerjik, merakli anlatici"
        target_duration_s = (45, 60)


def _narration(n_words: int) -> Narration:
    """Toplam ~n_words kelimelik gecerli bir Narration uret.

    NOT (plandan sapma): Beat.text 400 KARAKTER ile sinirli oldugu icin
    plandaki "tum filler'i tek beat'e yigan" yardimci >~53 kelimede pydantic
    ValidationError atiyordu. Bunun yerine filler kelimeler 3 beat'e esit
    dagitilir ve tek karakterlik ("o" — gecerli bir Turkce kelime) token
    kullanilir; boylece 400 kelimede bile hicbir beat 400 karakteri asmaz.
    Testin ASIL iddiasi (butce disi -> retry) korunur: word_count() ~ n_words.
    """
    base_beats = [
        ("Merkez bankasi faizi indirdi.", "FAIZ"),
        ("Piyasalar bunu beklemiyordu.", "SURPRIZ"),
        ("Kur ilk saatte yukseldi.", "KUR"),
    ]
    hook = "Bu karar neden herkesi sasirtti?"          # 5 kelime
    loop_close = "Iste bu yuzden herkes sasirdi."       # 5 kelime
    base_words = (len(hook.split()) + len(loop_close.split())
                  + sum(len(t.split()) for t, _ in base_beats))  # 21
    filler_total = max(0, n_words - base_words)
    per = [filler_total // 3] * 3
    for i in range(filler_total % 3):
        per[i] += 1

    beats = []
    for (text, on_screen), extra in zip(base_beats, per):
        if extra:
            text = text + " " + " ".join(["o"] * extra)
        beats.append(Beat(text=text, on_screen=on_screen))

    return Narration(
        hook=hook,
        beats=beats,
        loop_close=loop_close,
        mood="breaking",
    )


def test_word_budget_from_target_duration():
    assert word_budget((45, 60)) == (99, 132)   # 45*2.2, 60*2.2
    assert WORDS_PER_SECOND == 2.2


def test_word_budget_matches_measured_tts_speed():
    """Gercek ai33 kosumu: 70 kelime -> 31.4 sn (2.23 kelime/sn).
    Butcenin ust siniri 60 sn hedefini asmamali."""
    measured_wps = 70 / 31.4
    _, hi_words = word_budget((45, 60))
    assert hi_words / measured_wps <= 61.0


def test_prompt_contains_persona_and_budget():
    p = build_narration_prompt(_Item(), "Haber govdesi burada.", _Channel())
    assert "enerjik, merakli anlatici" in p
    lo_w, hi_w = word_budget(_Channel.voice.target_duration_s)
    assert str(lo_w) in p and str(hi_w) in p
    assert "loop_close" in p
    assert "Merkez bankasi faizi indirdi" in p


def test_prompt_requests_target_language_name():
    p = build_narration_prompt(_Item(), "govde", _Channel())
    # NOT (plandan sapma): LANGUAGE_NAMES["tr"] == "Türkçe" (plandaki "Turkish"
    # yalnizca bilinmeyen dil kodu icin fallback). Kanal dili "tr" oldugundan
    # prompt gercekte "Türkçe" icerir.
    assert "Türkçe" in p


def test_write_narration_returns_llm_output_when_in_budget(monkeypatch):
    good = _narration(130)
    calls = []

    def fake_run_json(prompt, schema, **kw):
        calls.append(prompt)
        return good

    monkeypatch.setattr("short_bot.narration_writer.run_json", fake_run_json)
    result = write_narration(_Item(), "govde", channel=_Channel())
    assert result is good
    assert len(calls) == 1   # butcede -> retry yok


def test_write_narration_retries_once_when_over_budget(monkeypatch):
    too_long = _narration(400)
    fixed = _narration(130)
    seq = [too_long, fixed]
    prompts = []

    def fake_run_json(prompt, schema, **kw):
        prompts.append(prompt)
        return seq.pop(0)

    monkeypatch.setattr("short_bot.narration_writer.run_json", fake_run_json)
    result = write_narration(_Item(), "govde", channel=_Channel())
    assert result is fixed
    assert len(prompts) == 2
    assert "KISALT" in prompts[1]        # geri bildirim eklendi


def test_write_narration_retries_once_when_under_budget(monkeypatch):
    too_short = _narration(30)
    fixed = _narration(130)
    seq = [too_short, fixed]
    prompts = []

    def fake_run_json(prompt, schema, **kw):
        prompts.append(prompt)
        return seq.pop(0)

    monkeypatch.setattr("short_bot.narration_writer.run_json", fake_run_json)
    write_narration(_Item(), "govde", channel=_Channel())
    assert "UZAT" in prompts[1]


def test_write_narration_accepts_second_attempt_even_if_off_budget(monkeypatch):
    """Ikinci deneme de butce disiysa yine de kabul edilir (sonsuz retry yok)."""
    still_long = _narration(400)

    monkeypatch.setattr("short_bot.narration_writer.run_json",
                        lambda p, s, **kw: still_long)
    assert write_narration(_Item(), "govde", channel=_Channel()) is still_long


def test_write_narration_requires_voice_config():
    class NoVoice:
        slug = "x"
        language = "tr"
        voice = None
    with pytest.raises(ValueError, match="voice"):
        write_narration(_Item(), "govde", channel=NoVoice())
