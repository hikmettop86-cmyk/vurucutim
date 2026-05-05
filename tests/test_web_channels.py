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
    (cfg_dir / "channels" / "demo-tr.yaml").write_text(
        "slug: demo-tr\nname: Demo TR\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: '0 * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}\n"
        "handle: '@demo'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite", scheduler=False)


def test_channels_list_shows_channel(app):
    client = app.test_client()
    resp = client.get("/channels")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "demo-tr" in body
    assert "Demo TR" in body
    assert "newscast" in body


def test_channel_edit_get_renders(app):
    client = app.test_client()
    resp = client.get("/channels/demo-tr/edit")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "demo-tr" in body
    assert "Demo TR" in body


def test_channel_edit_404_when_missing(app):
    client = app.test_client()
    resp = client.get("/channels/nonexistent/edit")
    assert resp.status_code == 404


def test_channel_edit_post_saves(app, tmp_path):
    client = app.test_client()
    resp = client.post("/channels/demo-tr/edit", data={
        "keywords": "yeni, kelimeler",
        "schedule_cron": "0 8,16 * * *",
        "handle": "@updated",
        "duration_s": "10",
        "min_score": "7.0",
        "enabled": "1",
    })
    assert resp.status_code in (200, 302)
    # Reload and verify persistence
    from short_bot.config import load_channel
    cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
    cfg = load_channel(cfg_dir / "channels" / "demo-tr.yaml")
    assert cfg.handle == "@updated"
    assert cfg.duration_s == 10
