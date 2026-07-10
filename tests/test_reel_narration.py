import pytest

from short_bot.reel_models import ReelBeat, ReelNarration
from short_bot.reel_narration import (WORDS_PER_SECOND, build_reel_prompt,
                                      reel_word_budget, write_reel_narration)


class _Reel:
    target_duration_s = (25, 45)


class _Channel:
    slug = "test-reel"
    language = "tr"
    reel = _Reel()


def _narr():
    """Bütçe içinde (55-99 kelime) tam senaryo — LLM'in 'iyi' çıktısı."""
    return ReelNarration(
        hook="Bir kaşık bal için arıların ne kadar çalıştığını asla tahmin edemezsin.",
        beats=[
            ReelBeat(text="İşçi arılar binlerce çiçeği tek tek dolaşarak nektar toplar.",
                     visual_query="bee on flower macro", keyword="NEKTAR"),
            ReelBeat(text="Topladıkları nektarı midelerindeki özel enzimlerle yavaşça bala dönüştürür.",
                     visual_query="honey bee closeup", keyword="ENZİM"),
            ReelBeat(text="Sonra bu sıvıyı kovandaki altıgen peteklere özenle biriktirirler.",
                     visual_query="honeycomb bees", keyword="PETEK"),
            ReelBeat(text="Kanat çırparak nektardaki fazla suyu buharlaştırıp balı koyulaştırırlar.",
                     visual_query="bees fanning wings hive", keyword="KURUTUR"),
            ReelBeat(text="Bir tek arı ömrü boyunca sadece bir çay kaşığı bal üretebilir.",
                     visual_query="single honey bee macro", keyword="BİR KAŞIK"),
        ],
        close="İşte o küçük kavanoz aslında binlerce arının tüm emeği.",
        mood="upbeat",
    )


def _short():
    """Bütçe altında (13 kelime) çıktı — retry tetikler."""
    return ReelNarration(
        hook="Bal nasıl olur?",
        beats=[
            ReelBeat(text="Arılar nektar toplar.", visual_query="bee flower", keyword="NEKTAR"),
            ReelBeat(text="Enzimlerle işler.", visual_query="bee macro", keyword="ENZİM"),
            ReelBeat(text="Peteğe biriktirir.", visual_query="honeycomb", keyword="PETEK"),
        ],
        close="İşte arının emeği.", mood="upbeat",
    )


def test_word_budget():
    assert reel_word_budget((25, 45)) == (55, 99)   # 25*2.2, 45*2.2
    assert WORDS_PER_SECOND == 2.2


def test_prompt_asks_concrete_english_queries_and_language():
    p = build_reel_prompt("bal ilginç bilgiler", _Channel())
    assert "visual_query" in p
    assert "English" in p            # görsel sorgular İngilizce
    assert "Turkish" in p            # seslendirme Türkçe
    assert "55" in p and "99" in p   # kelime bütçesi


def test_write_returns_llm_output_in_budget(monkeypatch):
    good = _narr()
    calls = []
    monkeypatch.setattr("short_bot.reel_narration.run_json",
                        lambda p, s, **kw: (calls.append(p), good)[1])
    result = write_reel_narration("bal", channel=_Channel())
    assert result is good
    assert len(calls) == 1


def test_write_retries_once_when_off_budget(monkeypatch):
    # ilk cikti cok kisa -> retry
    short = _short()
    fixed = _narr()
    seq = [short, fixed]; prompts = []
    monkeypatch.setattr("short_bot.reel_narration.run_json",
                        lambda p, s, **kw: (prompts.append(p), seq.pop(0))[1])
    result = write_reel_narration("bal", channel=_Channel())
    assert result is fixed
    assert len(prompts) == 2


def test_write_requires_reel_config():
    class NoReel:
        slug = "x"; language = "tr"; reel = None
    with pytest.raises(ValueError, match="reel"):
        write_reel_narration("bal", channel=NoReel())
