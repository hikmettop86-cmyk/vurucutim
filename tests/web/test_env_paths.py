"""Test env-var path overrides for create_app() — used by Electron runner."""
from pathlib import Path
from short_bot.web import create_app

MINIMAL_SETTINGS = (
    "ffmpeg_path: ffmpeg\n"
    "claude_cli_path: claude\n"
    "web:\n"
    "  host: 127.0.0.1\n"
    "  port: 5005\n"
)


def _write_settings(cfg_dir: Path) -> None:
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "settings.yaml").write_text(MINIMAL_SETTINGS, encoding="utf-8")


def test_env_overrides_apply(tmp_path, monkeypatch):
    cfg = tmp_path / "myconfig"
    out = tmp_path / "alt-output"
    _write_settings(cfg)
    monkeypatch.setenv("SHORT_BOT_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("SHORT_BOT_DATA_DIR", str(tmp_path / "alt-data"))
    monkeypatch.setenv("SHORT_BOT_LOGS_DIR", str(tmp_path / "alt-logs"))
    monkeypatch.setenv("SHORT_BOT_OUTPUT_ROOT", str(out))

    # Pass an explicit db_path that ignores SHORT_BOT_DATA_DIR — must STILL be overridden
    app = create_app(db_path=tmp_path / "explicit.db", scheduler=False)
    assert str(app.config["SHORTBOT_CONFIG_DIR"]) == str(cfg)
    assert str(app.config["SHORTBOT_OUTPUT_ROOT"]) == str(out)


def test_no_env_uses_defaults_or_args(tmp_path, monkeypatch):
    # Make sure none of the SHORT_BOT_* vars are set
    for k in ("SHORT_BOT_CONFIG_DIR", "SHORT_BOT_DATA_DIR", "SHORT_BOT_LOGS_DIR", "SHORT_BOT_OUTPUT_ROOT"):
        monkeypatch.delenv(k, raising=False)

    cfg = tmp_path / "fromarg"
    _write_settings(cfg)
    app = create_app(config_dir=cfg, db_path=tmp_path / "x.db", scheduler=False)
    assert str(app.config["SHORTBOT_CONFIG_DIR"]) == str(cfg)


def test_empty_data_dir_rejected(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("SHORT_BOT_DATA_DIR", "   ")
    with pytest.raises(ValueError, match="SHORT_BOT_DATA_DIR must be non-empty"):
        create_app(db_path=tmp_path / "x.db", scheduler=False)
