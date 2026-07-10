import pytest
import yaml
from pydantic import ValidationError

from short_bot.config import VoiceConfig, load_channel, save_channel

BASE = {
    "slug": "test-anlatici",
    "name": "Test Anlatici",
    "keywords": ["gundem"],
    "language": "tr",
    "schedule_cron": "0 9 * * *",
    "duration_s": 6,
    "min_score": 7.0,
    "max_candidates_per_run": 3,
    "template": "newscast",
    "colors": {"primary": "#b91c1c", "accent": "#ffea3b",
               "bg_gradient": ["#2a3a5e", "#11182f"]},
    "handle": "@test",
    "output_dir": "output/test",
}


def _write(tmp_path, extra):
    p = tmp_path / "test-anlatici.yaml"
    p.write_text(yaml.safe_dump({**BASE, **extra}, allow_unicode=True),
                 encoding="utf-8")
    return p


def test_channel_without_voice_block_has_none(tmp_path):
    cfg = load_channel(_write(tmp_path, {}))
    assert cfg.voice is None


def test_channel_with_voice_block_parses(tmp_path):
    p = _write(tmp_path, {"voice": {
        "enabled": True,
        "voice_id": "elevenlabs_abc123",
        "speed": 1.1,
        "persona": "enerjik anlatici",
        "target_duration_s": [45, 60],
    }})
    cfg = load_channel(p)
    assert cfg.voice.enabled is True
    assert cfg.voice.voice_id == "elevenlabs_abc123"
    assert cfg.voice.speed == 1.1
    assert cfg.voice.target_duration_s == (45, 60)
    assert cfg.voice.music_volume == 0.12  # default


def test_voice_enabled_without_voice_id_rejected():
    with pytest.raises(ValidationError, match="voice_id"):
        VoiceConfig(enabled=True, voice_id="  ")


def test_voice_disabled_without_voice_id_allowed():
    assert VoiceConfig(enabled=False).voice_id == ""


def test_voice_speed_out_of_range_rejected():
    with pytest.raises(ValidationError):
        VoiceConfig(enabled=False, speed=2.5)


def test_voice_target_duration_must_be_increasing():
    with pytest.raises(ValidationError, match="target_duration_s"):
        VoiceConfig(enabled=False, target_duration_s=(60, 45))


def test_save_channel_round_trips_voice(tmp_path):
    cfg = load_channel(_write(tmp_path, {"voice": {
        "enabled": True, "voice_id": "elevenlabs_abc123",
        "speed": 1.1, "target_duration_s": [40, 55],
    }}))
    out = tmp_path / "out.yaml"
    save_channel(out, cfg)
    again = load_channel(out)
    assert again.voice == cfg.voice


def test_save_channel_omits_voice_when_none(tmp_path):
    cfg = load_channel(_write(tmp_path, {}))
    out = tmp_path / "out.yaml"
    save_channel(out, cfg)
    assert "voice" not in yaml.safe_load(out.read_text(encoding="utf-8"))
