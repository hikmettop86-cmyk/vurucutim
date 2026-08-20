"""VoiceConfig.provider/model/volume/emotion — yükle/kaydet, geriye uyum."""
from __future__ import annotations

import pytest
import yaml

from short_bot.config import VoiceConfig, load_channel, save_channel

_BASE = """\
slug: sesli
name: Sesli
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@s'
output_dir: output/s
enabled: true
"""


def _write(tmp_path, voice_yaml: str):
    p = tmp_path / "s.yaml"
    p.write_text(_BASE + voice_yaml, encoding="utf-8")
    return p


def test_legacy_voice_block_defaults_to_ai33(tmp_path):
    cfg = load_channel(_write(tmp_path, "voice:\n  enabled: true\n  voice_id: abc\n  speed: 1.1\n"))
    assert cfg.voice.provider == "ai33"
    assert cfg.voice.model == "" and cfg.voice.volume == 1.0 and cfg.voice.emotion == ""
    out = tmp_path / "o.yaml"
    save_channel(out, cfg)
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))["voice"]
    assert raw["provider"] == "ai33"
    assert "model" not in raw and "volume" not in raw and "emotion" not in raw


def test_cartesia_fields_roundtrip(tmp_path):
    cfg = load_channel(_write(tmp_path,
        "voice:\n  enabled: true\n  provider: cartesia\n  voice_id: c1cf\n  speed: 1.05\n"
        "  model: sonic-preview\n  volume: 1.2\n  emotion: '[sakin]'\n"))
    v = cfg.voice
    assert (v.provider, v.model, v.volume, v.emotion) == ("cartesia", "sonic-preview", 1.2, "[sakin]")
    out = tmp_path / "o.yaml"
    save_channel(out, cfg)
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))["voice"]
    assert raw == {"enabled": True, "provider": "cartesia", "voice_id": "c1cf", "speed": 1.05,
                   "persona": v.persona, "target_duration_s": [45, 60], "music_volume": 0.12,
                   "model": "sonic-preview", "volume": 1.2, "emotion": "[sakin]"}


def test_cartesia_speed_below_api_floor_rejected():
    with pytest.raises(ValueError, match="0.6"):
        VoiceConfig(enabled=True, provider="cartesia", voice_id="v", speed=0.5)
    VoiceConfig(enabled=True, provider="ai33", voice_id="v", speed=0.5)   # ai33 0.5'e izin verir


def test_volume_range_enforced():
    with pytest.raises(ValueError):
        VoiceConfig(enabled=False, volume=3.0)
    with pytest.raises(ValueError):
        VoiceConfig(enabled=False, volume=0.1)


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        VoiceConfig(enabled=False, provider="google")
