import pytest

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
    logs_dir = tmp_path / "logs" / "runs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "20260505_140000_son-dakika.log").write_text(
        "line A\nline B\nline C\n", encoding="utf-8"
    )
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      logs_dir=logs_dir, scheduler=False)


def test_logs_page_renders(app):
    client = app.test_client()
    resp = client.get("/logs")
    assert resp.status_code == 200


def test_logs_tail_returns_recent_lines(app):
    client = app.test_client()
    resp = client.get("/logs/tail")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "line A" in body or "line B" in body or "line C" in body
