import pytest
import yaml

from short_bot.secrets_io import update_ai33_api_key
from short_bot.tts.ai33_client import normalize_voice_id, resolve_ai33_api_key


def test_resolve_from_secrets_dict():
    assert resolve_ai33_api_key({"ai33_api_key": "sk_secret"}) == "sk_secret"


def test_resolve_env_beats_secrets(monkeypatch):
    monkeypatch.setenv("AI33_API_KEY", "sk_env")
    assert resolve_ai33_api_key({"ai33_api_key": "sk_secret"}) == "sk_env"


def test_resolve_missing_returns_empty(monkeypatch):
    monkeypatch.delenv("AI33_API_KEY", raising=False)
    assert resolve_ai33_api_key({}) == ""


def test_update_ai33_api_key_upsert_and_clear(tmp_path):
    p = tmp_path / "secrets.yaml"
    p.write_text(yaml.safe_dump({"pexels_api_key": "keep"}), encoding="utf-8")

    update_ai33_api_key(p, "sk_new")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["ai33_api_key"] == "sk_new"
    assert data["pexels_api_key"] == "keep"   # diger anahtarlar korunur

    update_ai33_api_key(p, None)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert "ai33_api_key" not in data
    assert data["pexels_api_key"] == "keep"


@pytest.mark.parametrize("raw,expected", [
    ("abc123", "elevenlabs_abc123"),          # ham id -> elevenlabs prefix
    ("elevenlabs_abc123", "elevenlabs_abc123"),
    ("clone_2615683", "clone_2615683"),
    ("minimax_x", "minimax_x"),
    ("  abc123  ", "elevenlabs_abc123"),
])
def test_normalize_voice_id(raw, expected):
    assert normalize_voice_id(raw) == expected


def test_normalize_voice_id_empty_raises():
    with pytest.raises(ValueError, match="voice_id"):
        normalize_voice_id("   ")
