"""Settings page: youtube_api_key field + trends block read/write."""
from __future__ import annotations

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


def _base_form() -> dict:
    return {
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku", "model_script": "sonnet",
    }


# --- YouTube API key ---------------------------------------------------------

def test_settings_page_shows_youtube_api_key_input(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert 'name="youtube_api_key"' in body
    assert "YouTube Data API Key" in body or "YouTube" in body


def test_settings_save_youtube_api_key_writes_secrets(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    form = _base_form()
    form["youtube_api_key"] = "AIza-TEST-KEY-9999"
    resp = app.test_client().post("/settings", data=form)
    assert resp.status_code in (200, 302)
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert data["youtube_api_key"] == "AIza-TEST-KEY-9999"


def test_settings_clear_youtube_api_key_removes_it(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("youtube_api_key: OLDKEY\n", encoding="utf-8")
    form = _base_form()
    form["youtube_api_key"] = ""
    form["youtube_api_key_clear"] = "1"
    app.test_client().post("/settings", data=form)
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    assert data.get("youtube_api_key", "") == ""


def test_settings_omit_youtube_api_key_preserves_existing(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("youtube_api_key: KEEP_ME\n", encoding="utf-8")
    form = _base_form()
    form["youtube_api_key"] = ""
    app.test_client().post("/settings", data=form)
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert data["youtube_api_key"] == "KEEP_ME"


def test_youtube_key_shown_masked_when_set(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("youtube_api_key: AIzaSyABCDEF12345XYZ\n", encoding="utf-8")
    body = app.test_client().get("/settings").data.decode("utf-8")
    # masked output: bullets + last 4
    assert "5XYZ" in body
    # raw secret must NOT appear
    assert "AIzaSyABCDEF12345XYZ" not in body


# --- Trends block ------------------------------------------------------------

def test_settings_page_shows_trends_section(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "Trend Detection" in body
    assert 'name="trends_enabled"' in body
    assert 'name="trends_refresh_minutes"' in body
    assert 'name="trends_src_google_daily"' in body
    assert 'name="trends_src_youtube"' in body


def test_settings_save_trends_block_persists_to_yaml(app, tmp_path):
    cfg_path = tmp_path / "config" / "settings.yaml"
    form = _base_form()
    form["trends_enabled"] = "1"
    form["trends_refresh_minutes"] = "45"
    form["trends_cache_max_age_minutes"] = "120"
    form["trends_src_google_daily"] = "1"
    form["trends_src_youtube"] = "1"
    app.test_client().post("/settings", data=form)

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert data["trends"]["enabled"] is True
    assert data["trends"]["refresh_minutes"] == 45
    assert data["trends"]["cache_max_age_minutes"] == 120.0
    assert set(data["trends"]["default_sources"]) == {"google_daily", "youtube"}


def test_settings_save_trends_disabled_persists(app, tmp_path):
    cfg_path = tmp_path / "config" / "settings.yaml"
    form = _base_form()
    # trends_enabled NOT set in form -> should write enabled: false
    form["trends_refresh_minutes"] = "60"
    app.test_client().post("/settings", data=form)
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert data["trends"]["enabled"] is False


def test_settings_save_trends_single_source(app, tmp_path):
    cfg_path = tmp_path / "config" / "settings.yaml"
    form = _base_form()
    form["trends_enabled"] = "1"
    form["trends_src_google_daily"] = "1"
    # youtube checkbox NOT submitted
    app.test_client().post("/settings", data=form)
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert data["trends"]["default_sources"] == ["google_daily"]
