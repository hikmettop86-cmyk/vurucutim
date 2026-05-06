import pytest
import yaml

from short_bot.web import create_app


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
