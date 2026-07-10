"""Voiced kanal sablonu gecerli mi + [voice] extra tanimli mi.

Gercek kanal YAML'lari kullaniciya ozel ve .gitignore'da (`config/channels/*.yaml`),
bu yuzden pilot kanalin birebir kopyasi burada fixture olarak tutulur. Panelden
kanal olustururken uretilen voice blogunun sematik olarak gecerli kaldigini
dogrular.
"""
from pathlib import Path

import tomllib

from short_bot.config import load_channel

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANNEL = Path(__file__).parent / "fixtures" / "voice_channel.yaml"


def test_pilot_channel_loads():
    cfg = load_channel(CHANNEL)
    assert cfg.slug == "test-anlatici"
    assert cfg.voice is not None and cfg.voice.enabled is True
    assert cfg.voice.target_duration_s == (45, 60)
    assert cfg.language == "tr"


def test_pilot_channel_does_not_auto_upload():
    """Pilot: mevcut kanallari riske atmadan, elle onayla yuklenir."""
    cfg = load_channel(CHANNEL)
    assert cfg.youtube is None or cfg.youtube.auto_upload is False


def test_pilot_channel_uses_narrator_template():
    assert load_channel(CHANNEL).template == "narrator"


def test_pilot_channel_is_disabled_so_scheduler_skips_it():
    """Pilot kanal cron'a takilmamali; elle calistirilir."""
    assert load_channel(CHANNEL).enabled is False


def test_voice_extra_declared_in_pyproject():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    assert "voice" in extras
    assert any("whisperx" in dep for dep in extras["voice"])
