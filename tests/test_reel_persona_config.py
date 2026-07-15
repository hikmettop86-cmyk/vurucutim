"""ReelConfig.persona alanı — reel anlatım tonu işareti.

Boş varsayılan KRİTİK: mevcut tüm kanallar persona="" ile bugünkü prompt'u alır
→ sıfır regresyon.
"""


def test_reelconfig_persona_default_bos():
    from short_bot.config import ReelConfig
    c = ReelConfig(enabled=False)
    assert c.persona == ""


def test_reelconfig_persona_set():
    from short_bot.config import ReelConfig
    c = ReelConfig(enabled=False, persona="vahsi_mizah")
    assert c.persona == "vahsi_mizah"


def test_persona_channel_data_roundtrip(tmp_path):
    from short_bot.config import (ChannelConfig, ReelConfig, save_channel,
                                  load_channel)
    cfg = ChannelConfig(
        slug="test-ch", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, cta_enabled=True, cta_text="x", cta_icons=[],
        cta_duration_s=4, cta_show_handle=True, language="tr",
        max_age_hours=24,
        reel=ReelConfig(enabled=True, voice_id="v1", persona="vahsi_mizah"),
    )
    p = tmp_path / "ch.yaml"
    save_channel(p, cfg)
    assert load_channel(p).reel.persona == "vahsi_mizah"
