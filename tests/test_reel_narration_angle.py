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


def test_hook_angle_appended_to_prompt(monkeypatch):
    seen = {}

    def fake(prompt, schema, **kw):
        seen["p"] = prompt
        return _narr()

    monkeypatch.setattr("short_bot.reel_narration.run_json", fake)
    write_reel_narration("bal", channel=_Ch(),
                         hook_angle="Açılışı bir SORU olarak kur.")
    assert "AÇILIŞ AÇISI" in seen["p"]
    assert "Açılışı bir SORU olarak kur." in seen["p"]


def test_no_hook_angle_no_directive(monkeypatch):
    seen = {}
    monkeypatch.setattr("short_bot.reel_narration.run_json",
                        lambda p, s, **kw: (seen.__setitem__("p", p), _narr())[1])
    write_reel_narration("bal", channel=_Ch(), hook_angle="")
    assert "AÇILIŞ AÇISI" not in seen["p"]
