"""Test /healthz endpoint — used by Electron to detect Flask readiness."""
import pytest
from short_bot.web import create_app


@pytest.fixture
def client(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\n"
        "claude_cli_path: claude\n"
        "web:\n"
        "  host: 127.0.0.1\n"
        "  port: 5005\n",
        encoding="utf-8",
    )
    app = create_app(
        config_dir=config_dir,
        db_path=tmp_path / "test.db",
        templates_dir=tmp_path / "templates",
        music_root=tmp_path / "music",
        cache_dir=tmp_path / "cache",
        lock_dir=tmp_path / "locks",
        logs_dir=tmp_path / "logs",
        output_root=tmp_path / "output",
        scheduler=False,
    )
    app.config["TESTING"] = True
    return app.test_client()


def test_healthz_returns_ok(client):
    rv = client.get("/healthz")
    assert rv.status_code == 200
    assert rv.json == {"status": "ok", "version": rv.json["version"]}


def test_healthz_includes_version(client):
    rv = client.get("/healthz")
    assert "version" in rv.json
    assert isinstance(rv.json["version"], str)
    assert len(rv.json["version"]) > 0
