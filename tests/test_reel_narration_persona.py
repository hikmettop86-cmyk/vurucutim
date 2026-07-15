"""Persona enjeksiyonu + mizah kapısı wiring (reel_narration)."""
import pytest

from short_bot.config import ChannelConfig, ReelConfig
from short_bot.reel_models import ReelBeat, ReelNarration


def _kanal(persona=""):
    return ChannelConfig(
        slug="test-ch", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False, language="tr", max_age_hours=24,
        reel=ReelConfig(enabled=True, voice_id="v1", persona=persona,
                        target_duration_s=(25, 45), cta_enabled=False,
                        comment_question=False, series_enabled=False),
    )


def _sahte_narration():
    return ReelNarration(
        hook="Bir soru cümlesi burada duruyor bakalım.",
        beats=[ReelBeat(text="Birinci beat cümlesi burada.", visual_query="crow", keyword="A"),
               ReelBeat(text="İkinci beat cümlesi burada.", visual_query="bird", keyword="B"),
               ReelBeat(text="Üçüncü beat cümlesi burada.", visual_query="nest", keyword="C")],
        close="Ve işte bir soru cümlesi burada duruyor.", mood="neutral")


def test_persona_promptu_enjekte_edilir(monkeypatch):
    import short_bot.reel_narration as RN
    yakalanan = {}

    def sahte_run_json(prompt, schema, **kw):
        yakalanan["prompt"] = prompt
        return _sahte_narration()

    monkeypatch.setattr(RN, "run_json", sahte_run_json)
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    monkeypatch.setattr(RN, "check_humor", lambda *a, **k: [], raising=False)
    RN.write_reel_narration("karga", channel=_kanal("vahsi_mizah"))
    assert "ANLATIM PERSONASI" in yakalanan["prompt"]
    assert "istihbarat teşkilatı" in yakalanan["prompt"]  # few-shot metni


def test_personasiz_prompt_degismez(monkeypatch):
    import short_bot.reel_narration as RN
    yakalanan = {}

    def sahte_run_json(prompt, schema, **kw):
        yakalanan["prompt"] = prompt
        return _sahte_narration()

    monkeypatch.setattr(RN, "run_json", sahte_run_json)
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    RN.write_reel_narration("karga", channel=_kanal(""))
    assert "ANLATIM PERSONASI" not in yakalanan["prompt"]   # sıfır regresyon


def test_mizah_kapisi_zayif_senaryoyu_reddeder(monkeypatch):
    import short_bot.reel_narration as RN
    from short_bot.reel_humor_check import HumorIssue
    monkeypatch.setattr(RN, "run_json", lambda p, s, **k: _sahte_narration())
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    monkeypatch.setattr(RN, "check_humor",
                        lambda *a, **k: [HumorIssue(problem="zorlama", kind="humor")],
                        raising=False)
    with pytest.raises(ValueError, match="mizah denetiminden geçemedi"):
        RN.write_reel_narration("karga", channel=_kanal("vahsi_mizah"))


def test_mizah_kapisi_personasiz_calismaz(monkeypatch):
    import short_bot.reel_narration as RN
    monkeypatch.setattr(RN, "run_json", lambda p, s, **k: _sahte_narration())
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    cagrildi = {"n": 0}

    def sayan(*a, **k):
        cagrildi["n"] += 1
        return []

    monkeypatch.setattr(RN, "check_humor", sayan, raising=False)
    RN.write_reel_narration("karga", channel=_kanal(""))   # persona yok
    assert cagrildi["n"] == 0       # mizah kapısı personasız çağrılmamalı


def test_mizah_olgu_kapisini_atlar(monkeypatch):
    """Persona varken olgu kapısı (check_narration) ÇAĞRILMAZ — mizahi abartıyı
    yanlış-bilgi sanıp gereksiz yeniden yazım tetikliyordu (run 907). Biyoloji
    doğruluğunu mizah kapısı denetler."""
    import short_bot.reel_narration as RN
    monkeypatch.setattr(RN, "run_json", lambda p, s, **k: _sahte_narration())
    cagrildi = {"olgu": 0}

    def sayan_olgu(*a, **k):
        cagrildi["olgu"] += 1
        return []

    monkeypatch.setattr(RN, "check_narration", sayan_olgu)
    monkeypatch.setattr(RN, "check_humor", lambda *a, **k: [], raising=False)
    RN.write_reel_narration("bal porsuğu", channel=_kanal("vahsi_mizah"))
    assert cagrildi["olgu"] == 0        # persona'da olgu kapısı atlanmalı


def test_personasiz_olgu_kapisi_calisir(monkeypatch):
    """Regresyon: persona YOKken olgu kapısı normal çalışır."""
    import short_bot.reel_narration as RN
    monkeypatch.setattr(RN, "run_json", lambda p, s, **k: _sahte_narration())
    cagrildi = {"olgu": 0}

    def sayan_olgu(*a, **k):
        cagrildi["olgu"] += 1
        return []

    monkeypatch.setattr(RN, "check_narration", sayan_olgu)
    RN.write_reel_narration("bal porsuğu", channel=_kanal(""))
    assert cagrildi["olgu"] == 1        # personasız olgu kapısı çalışır
