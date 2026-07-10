from pathlib import Path

from short_bot.config import load_channel

CHANNEL = Path(__file__).parent / "fixtures" / "reel_channel.yaml"


def test_pilot_reel_channel_loads():
    cfg = load_channel(CHANNEL)
    assert cfg.slug == "test-reel"
    assert cfg.content_source == "generator"
    assert cfg.reel is not None and cfg.reel.enabled is True
    assert cfg.reel.target_duration_s == (25, 45)


def test_pilot_reel_channel_disabled_by_default():
    assert load_channel(CHANNEL).enabled is False


def test_pilot_reel_channel_no_auto_upload():
    cfg = load_channel(CHANNEL)
    assert cfg.youtube is None or cfg.youtube.auto_upload is False
