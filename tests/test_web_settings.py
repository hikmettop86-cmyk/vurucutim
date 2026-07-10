import pytest
import yaml

from short_bot.web import create_app


@pytest.fixture(autouse=True)
def _mock_catalog():
    from unittest.mock import patch
    with patch("short_bot.web.routes.settings.get_catalog",
               return_value={"groups": [{"label": "Anthropic Claude", "models": [
                   {"id": "anthropic/claude-x", "label": "Claude X", "vision": True}]}]}):
        yield


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / "data"
    secrets_dir.mkdir()
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=secrets_dir / "secrets.yaml",
                      scheduler=False)


def test_settings_page_shows_pexels_key_field_unset(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "Pexels" in body
    assert 'name="pexels_api_key"' in body  # input element present


def test_settings_save_pexels_key_writes_secrets_file(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    resp = app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg",
        "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85",
        "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "pexels_api_key": "MYTESTKEY",
    })
    assert resp.status_code in (200, 302)
    assert secrets_path.exists()
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert data["pexels_api_key"] == "MYTESTKEY"


def test_settings_save_empty_pexels_key_clears(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("pexels_api_key: OLDKEY\n", encoding="utf-8")
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "pexels_api_key": "",
        "pexels_api_key_clear": "1",
    })
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    assert data.get("pexels_api_key", "") == ""


def test_settings_page_shows_ai33_key_field(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert 'name="ai33_api_key"' in body
    assert "ai33" in body.lower() or "Seslendirme" in body


def test_settings_page_masks_existing_ai33_key(app, tmp_path):
    (tmp_path / "data" / "secrets.yaml").write_text(
        "ai33_api_key: sk_9secretpart\n", encoding="utf-8")
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "sk_9secretpart" not in body      # ham anahtar asla sizmamali
    assert "part" in body                     # maskeli son 4 karakter


def test_settings_save_ai33_key_writes_secrets_file(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    resp = app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "ai33_api_key": "sk_myAi33Key",
    })
    assert resp.status_code in (200, 302)
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert data["ai33_api_key"] == "sk_myAi33Key"


def test_settings_save_clears_ai33_key(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("ai33_api_key: sk_OLD\n", encoding="utf-8")
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "ai33_api_key": "", "ai33_api_key_clear": "1",
    })
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    assert data.get("ai33_api_key", "") == ""


def test_settings_save_omits_ai33_key_does_not_overwrite(app, tmp_path):
    """ai33_api_key_clear yok + bos deger → mevcut anahtar korunur."""
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("ai33_api_key: sk_KEEP\n", encoding="utf-8")
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "ai33_api_key": "",
    })
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    assert data.get("ai33_api_key") == "sk_KEEP"


def test_settings_save_omits_pexels_key_does_not_overwrite(app, tmp_path):
    """No `pexels_api_key_clear` flag and empty value → preserve existing key."""
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("pexels_api_key: KEEPER\n", encoding="utf-8")
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "pexels_api_key": "",
    })
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert data["pexels_api_key"] == "KEEPER"


def test_settings_save_writes_ai_backend_and_models(app, tmp_path):
    settings_path = tmp_path / "config" / "settings.yaml"
    resp = app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku", "model_script": "sonnet",
        "ai_backend": "openrouter",
        "or_model_dna": "anthropic/claude-opus-4.8",
        "or_model_default": "google/gemini-2.5-flash",
        "or_model_script": "anthropic/claude-sonnet-4.6",
        "openrouter_api_key": "sk-or-secret",
    })
    assert resp.status_code in (200, 302)
    data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert data["ai_backend"] == "openrouter"
    assert data["openrouter_models"]["dna"] == "anthropic/claude-opus-4.8"
    assert data["openrouter_models"]["default"] == "google/gemini-2.5-flash"
    secrets = yaml.safe_load((tmp_path / "data" / "secrets.yaml").read_text(encoding="utf-8"))
    assert secrets["openrouter_api_key"] == "sk-or-secret"


def test_settings_custom_or_model_overrides_dropdown(app, tmp_path):
    settings_path = tmp_path / "config" / "settings.yaml"
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku", "model_script": "sonnet",
        "ai_backend": "openrouter",
        "or_model_default": "__custom__",
        "or_model_default_custom": "x-ai/grok-2",
        "or_model_dna": "anthropic/claude-opus-4.8",
        "or_model_script": "anthropic/claude-sonnet-4.6",
    })
    data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert data["openrouter_models"]["default"] == "x-ai/grok-2"


def test_settings_clear_openrouter_key(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("openrouter_api_key: OLD\n", encoding="utf-8")
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku", "model_script": "sonnet",
        "ai_backend": "claude_cli",
        "openrouter_api_key": "", "openrouter_api_key_clear": "1",
    })
    secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    assert secrets.get("openrouter_api_key", "") == ""


def test_settings_page_shows_openrouter_fields(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert 'name="ai_backend"' in body
    assert 'name="openrouter_api_key"' in body
    assert 'name="or_model_default"' in body
    assert "OpenRouter" in body


def test_settings_save_writes_vision_model(app, tmp_path):
    settings_path = tmp_path / "config" / "settings.yaml"
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku", "model_script": "sonnet",
        "ai_backend": "openrouter",
        "or_model_dna": "anthropic/claude-opus-4.8",
        "or_model_default": "google/gemini-2.5-flash",
        "or_model_script": "anthropic/claude-sonnet-4.6",
        "or_model_vision": "google/gemma-4-31b-it",
    })
    data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert data["openrouter_models"]["vision"] == "google/gemma-4-31b-it"


def test_settings_page_shows_vision_dropdown(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert 'name="or_model_vision"' in body


def test_settings_view_uses_dynamic_catalog(app):
    from unittest.mock import patch
    fake = {"groups": [{"label": "Anthropic Claude",
                        "models": [{"id": "anthropic/live-model", "label": "Live", "vision": True}]}]}
    with patch("short_bot.web.routes.settings.get_catalog", return_value=fake):
        body = app.test_client().get("/settings").data.decode("utf-8")
    assert "anthropic/live-model" in body


def test_vision_dropdown_only_shows_vision_models(app):
    from unittest.mock import patch
    import re
    fake = {"groups": [{"label": "Anthropic Claude", "models": [
        {"id": "anthropic/vis", "label": "Vis", "vision": True},
        {"id": "anthropic/novis", "label": "NoVis", "vision": False},
    ]}]}
    with patch("short_bot.web.routes.settings.get_catalog", return_value=fake):
        body = app.test_client().get("/settings").data.decode("utf-8")
    m = re.search(r'name="or_model_vision".*?</select>', body, re.DOTALL)
    assert m, "vision dropdown bulunamadi"
    vision_block = m.group(0)
    assert "anthropic/vis" in vision_block
    assert "anthropic/novis" not in vision_block
