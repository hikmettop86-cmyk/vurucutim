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
        "claude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo.yaml").write_text("""\
slug: demo
name: Demo
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@demo'
output_dir: output/demo
enabled: true
cta:
  enabled: false
  text: ''
  icons: []
  duration_s: 0
  show_handle: false
""", encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      scheduler=False)


def test_edit_page_shows_bg_video_section(app):
    body = app.test_client().get("/channels/demo/edit").data.decode("utf-8")
    assert "Arka plan videosu" in body or "bg_video" in body
    assert 'name="bg_video_enabled"' in body
    assert "0.88" in body
    assert "0.80" in body


def test_edit_post_enables_bg_video_writes_yaml(app, tmp_path):
    client = app.test_client()
    client.get("/channels/demo/edit")
    resp = client.post("/channels/demo/edit", data={
        "schedule_cron": "0 * * * *",
        "duration_s": "6", "min_score": "6.0",
        "max_candidates_per_run": "5",
        "handle": "@demo",
        "enabled": "1",
        "bg_video_enabled": "on",
        "bg_video_scale": "0.88",
        "bg_video_blur_px": "30",
        "bg_video_dim": "0.4",
    })
    assert resp.status_code in (200, 302)
    yaml_path = tmp_path / "config" / "channels" / "demo.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert raw["bg_video"]["enabled"] is True
    assert raw["bg_video"]["scale"] == 0.88


def test_edit_post_disables_bg_video_omits_block(app, tmp_path):
    """Submitting without bg_video_enabled should remove the block from YAML."""
    yaml_path = tmp_path / "config" / "channels" / "demo.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    raw["bg_video"] = {"enabled": True, "scale": 0.80, "blur_px": 20, "dim": 0.3}
    yaml_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")

    client = app.test_client()
    client.get("/channels/demo/edit")
    client.post("/channels/demo/edit", data={
        "schedule_cron": "0 * * * *",
        "duration_s": "6", "min_score": "6.0",
        "max_candidates_per_run": "5",
        "handle": "@demo", "enabled": "1",
        # bg_video_enabled omitted
    })
    raw_after = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert "bg_video" not in raw_after
