import pytest
import yaml
from pydantic import ValidationError

from short_bot.config import ReelConfig, load_channel, save_channel

BASE = {
    "slug": "test-reel", "name": "Test Reel", "keywords": ["x"],
    "language": "tr", "schedule_cron": "0 9 * * *", "duration_s": 6,
    "min_score": 7.0, "max_candidates_per_run": 3, "template": "newscast",
    "colors": {"primary": "#0ea5e9", "accent": "#facc15",
               "bg_gradient": ["#0f172a", "#020617"]},
    "handle": "@testreel", "output_dir": "output/test-reel",
    "content_source": "generator",
    "generator": {"topic": "ilginc bilgiler ve nasil calisir aciklamalari"},
}


def _write(tmp_path, extra):
    p = tmp_path / "test-reel.yaml"
    p.write_text(yaml.safe_dump({**BASE, **extra}, allow_unicode=True), encoding="utf-8")
    return p


def test_channel_without_reel_block_has_none(tmp_path):
    assert load_channel(_write(tmp_path, {})).reel is None


def test_channel_with_reel_block_parses(tmp_path):
    cfg = load_channel(_write(tmp_path, {"reel": {
        "enabled": True, "voice_id": "elevenlabs_abc", "speed": 1.1,
        "target_duration_s": [25, 45], "cut_pacing": "fast",
        "highlight_color": "#ff0000", "arrows_enabled": True,
        "arrow_color": "#ff2d2d", "arrow_frequency": "beats",
        "music_mood": "upbeat", "verify_footage": True,
    }}))
    assert cfg.reel.enabled is True
    assert cfg.reel.voice_id == "elevenlabs_abc"
    assert cfg.reel.target_duration_s == (25, 45)
    assert cfg.reel.cut_pacing == "fast"
    # Ducking açıkken bu, müziğin BOŞLUKTAKİ seviyesi (0.10 "gömülü" değeri artık
    # gereksiz — müzik konuşma altında kompresörle zaten çekiliyor)
    assert cfg.reel.music_volume == 0.30  # default


def test_reel_enabled_without_voice_id_rejected():
    with pytest.raises(ValidationError, match="voice_id"):
        ReelConfig(enabled=True, voice_id="  ")


def test_reel_disabled_without_voice_id_allowed():
    assert ReelConfig(enabled=False).voice_id == ""


def test_reel_bad_target_duration_rejected():
    with pytest.raises(ValidationError, match="target_duration_s"):
        ReelConfig(enabled=False, target_duration_s=(45, 25))


def test_reel_speed_out_of_range_rejected():
    with pytest.raises(ValidationError):
        ReelConfig(enabled=False, speed=2.5)


def test_save_channel_round_trips_reel(tmp_path):
    cfg = load_channel(_write(tmp_path, {"reel": {
        "enabled": True, "voice_id": "elevenlabs_abc", "cut_pacing": "slow",
        "target_duration_s": [20, 40]}}))
    out = tmp_path / "out.yaml"
    save_channel(out, cfg)
    assert load_channel(out).reel == cfg.reel


def test_save_channel_omits_reel_when_none(tmp_path):
    cfg = load_channel(_write(tmp_path, {}))
    out = tmp_path / "out.yaml"
    save_channel(out, cfg)
    assert "reel" not in yaml.safe_load(out.read_text(encoding="utf-8"))


def test_footage_driven_defaults_false(tmp_path):
    # SIFIR REGRESYON: bloğu olan mevcut tüm kanallar senaryo-önce kalmalı.
    cfg = load_channel(_write(tmp_path, {"reel": {
        "enabled": True, "voice_id": "v1", "target_duration_s": [45, 60]}}))
    assert cfg.reel.footage_driven is False


def test_footage_driven_parses_and_round_trips(tmp_path):
    cfg = load_channel(_write(tmp_path, {"reel": {
        "enabled": True, "voice_id": "v1", "target_duration_s": [45, 60],
        "footage_driven": True}}))
    assert cfg.reel.footage_driven is True
    # save → load round-trip (to_channel_data alanı yazmalı)
    p2 = tmp_path / "rt.yaml"
    save_channel(p2, cfg)
    assert load_channel(p2).reel.footage_driven is True
