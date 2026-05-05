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
        "slug: demo-tr\nname: Demo\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: ''\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}\n"
        "handle: '@demo'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite", scheduler=False)


def test_preview_returns_html(app):
    client = app.test_client()
    resp = client.get("/preview/demo-tr")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    body = resp.data.decode("utf-8")
    assert "ARA ZAM" in body  # from sample_script_tr.json
    assert "BEĞEN" in body    # UI labels for tr


def test_preview_404_for_missing_channel(app):
    client = app.test_client()
    resp = client.get("/preview/nonexistent")
    assert resp.status_code == 404


def test_preview_overrides_primary_color(app):
    client = app.test_client()
    resp = client.get("/preview/demo-tr?primary=%23ff00ff")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "#ff00ff" in body
