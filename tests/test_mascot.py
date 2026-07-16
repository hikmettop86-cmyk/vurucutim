"""Maskot (tekrar eden ana karakter) sistemi."""


def test_reelconfig_mascot_alanlari():
    from short_bot.config import ReelConfig
    c = ReelConfig(enabled=False, mascot_name="Deli Kâzım",
                   mascot_animal="bal porsuğu", mascot_trait="korkusuz")
    assert c.mascot_name == "Deli Kâzım"
    assert c.mascot_animal == "bal porsuğu"


def test_mascot_block_uc_alan_dolu():
    from short_bot.persona import mascot_block
    b = mascot_block("Deli Kâzım", "bal porsuğu", "Geri Vitesi Olmayan Deli")
    assert "Deli Kâzım" in b
    assert "ANA KARAKTER" in b
    assert "coğrafi tutarlılık" in b or "yanına gitmez" in b


def test_mascot_block_eksik_alan_bos():
    from short_bot.persona import mascot_block
    assert mascot_block("Deli Kâzım", "", "korkusuz") == ""   # animal eksik
    assert mascot_block("", "bal porsuğu", "korkusuz") == ""  # name eksik


def test_mascot_promptta_persona_ile(monkeypatch):
    import short_bot.reel_narration as RN
    from short_bot.config import ChannelConfig, ReelConfig
    from short_bot.reel_models import ReelBeat, ReelNarration
    yakalanan = {}

    def sahte(prompt, schema, **kw):
        yakalanan["prompt"] = prompt
        return ReelNarration(
            hook="Bir soru cümlesi burada.",
            beats=[ReelBeat(text="Beat cümlesi burada.", visual_query="x1", keyword="A"),
                   ReelBeat(text="Beat iki cümlesi.", visual_query="x2", keyword="B"),
                   ReelBeat(text="Beat üç cümlesi.", visual_query="x3", keyword="C")],
            close="Ve işte bir soru cümlesi.", mood="neutral")

    monkeypatch.setattr(RN, "run_json", sahte)
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    monkeypatch.setattr(RN, "check_humor", lambda *a, **k: [], raising=False)
    ch = ChannelConfig(
        slug="m", name="M", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast", colors={"primary": "#fff"},
        handle="@m", output_dir="o", enabled=True, language="tr",
        max_age_hours=24,
        reel=ReelConfig(enabled=True, voice_id="v1", persona="vahsi_mizah",
                        target_duration_s=(25, 45),                        comment_question=False, series_enabled=False,
                        mascot_name="Deli Kâzım", mascot_animal="bal porsuğu",
                        mascot_trait="korkusuz deli"))
    RN.write_reel_narration("penguen", channel=ch)
    assert "Deli Kâzım" in yakalanan["prompt"]
    assert "ANA KARAKTER" in yakalanan["prompt"]
