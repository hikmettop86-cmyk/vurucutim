from short_bot.reel_narration import write_reel_narration


class _Reel:
    target_duration_s = (25, 45)


class _Ch:
    slug = "c"; language = "tr"; reel = _Reel()


def _narr():
    from short_bot.reel_models import ReelBeat, ReelNarration
    return ReelNarration(
        hook="Bal nasıl yapılır acaba?",
        beats=[ReelBeat(text="Arılar nektar toplar bugün.", visual_query="bee flower", keyword="NEKTAR"),
               ReelBeat(text="Enzimlerle bunu işler hemen.", visual_query="bee macro", keyword="ENZİM"),
               ReelBeat(text="Peteğe biriktirir sonunda.", visual_query="honeycomb", keyword="PETEK")],
        close="İşte binlerce arının emeği bu.", mood="upbeat")


def _run(monkeypatch, **kw):
    seen = {}
    monkeypatch.setattr("short_bot.reel_narration.run_json",
                        lambda p, s, **k: (seen.__setitem__("p", p), _narr())[1])
    write_reel_narration("bal", channel=_Ch(), **kw)
    return seen["p"]


def test_series_directive_in_prompt(monkeypatch):
    p = _run(monkeypatch, series_directive="Bu bir 'Tuhaf Gerçekler' serisi bölümü.")
    assert "Tuhaf Gerçekler" in p


def test_comment_line_in_prompt(monkeypatch):
    p = _run(monkeypatch, comment_line="Hangisi seni şaşırttı?")
    assert "Hangisi seni şaşırttı?" in p


def test_no_bits_no_directives(monkeypatch):
    p = _run(monkeypatch)
    # sadece direktif yoksa seri/yorum metni prompt'ta olmamalı:
    assert "serisi bölümü" not in p
