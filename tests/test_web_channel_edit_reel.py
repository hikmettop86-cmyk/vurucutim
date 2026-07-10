import pytest
import yaml

from short_bot.config import load_channel
from short_bot.web import create_app

CHANNEL_YAML = """\
slug: test-reel
name: Test Reel
keywords: [x]
language: tr
schedule_cron: 0 9 * * *
duration_s: 6
min_score: 7.0
max_candidates_per_run: 3
template: newscast
colors: {primary: '#0ea5e9', accent: '#facc15', bg_gradient: ['#0f172a', '#020617']}
handle: '@testreel'
output_dir: output/test-reel
content_source: generator
generator: {topic: ilginc bilgiler ve nasil calisir aciklamalari uzun}
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
"""


@pytest.fixture
def app(tmp_path):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n", encoding="utf-8")
    (cfg / "channels" / "test-reel.yaml").write_text(CHANNEL_YAML, encoding="utf-8")
    return create_app(config_dir=cfg, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml", scheduler=False)


def _path(app):
    return app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "test-reel.yaml"


def _add_reel(app, reel):
    p = _path(app); data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["reel"] = reel; p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _form(**over):
    f = {"schedule_cron": "0 9 * * *", "duration_s": "6", "min_score": "7.0",
         "max_candidates_per_run": "3", "max_age_hours": "24", "handle": "@testreel",
         "enabled": "1", "cta_enabled": "0", "cta_text": "", "cta_duration_s": "0",
         "cta_show_handle": "0", "keywords": "x", "content_source": "generator"}
    f.update(over); return f


def test_edit_page_shows_reel_section(app):
    body = app.test_client().get("/channels/test-reel/edit").data.decode("utf-8")
    assert 'name="reel_enabled"' in body
    assert 'name="reel_voice_id"' in body
    assert 'name="reel_cut_pacing"' in body


def test_post_without_reel_fields_preserves_reel(app):
    path = _add_reel(app, {"enabled": True, "voice_id": "elevenlabs_keep", "cut_pacing": "fast"})
    app.test_client().post("/channels/test-reel/edit", data=_form())
    cfg = load_channel(path)
    assert cfg.reel is not None and cfg.reel.voice_id == "elevenlabs_keep"


def test_post_does_not_inject_reel_into_plain_channel(app):
    path = _path(app)
    app.test_client().post("/channels/test-reel/edit", data=_form(
        reel_voice_id="", reel_cut_pacing="medium", reel_music_mood="upbeat"))
    assert load_channel(path).reel is None


def test_post_enabling_reel_creates_block(app):
    path = _path(app)
    app.test_client().post("/channels/test-reel/edit", data=_form(
        reel_enabled="on", reel_voice_id="elevenlabs_new", reel_cut_pacing="slow",
        reel_music_mood="calm", reel_target_min="20", reel_target_max="40"))
    cfg = load_channel(path)
    assert cfg.reel.enabled is True and cfg.reel.voice_id == "elevenlabs_new"
    assert cfg.reel.cut_pacing == "slow" and cfg.reel.target_duration_s == (20, 40)


def test_post_enabling_reel_without_voice_flashes_error(app):
    path = _path(app)
    resp = app.test_client().post("/channels/test-reel/edit",
                                  data=_form(reel_enabled="on", reel_voice_id=" "),
                                  follow_redirects=True)
    assert resp.status_code == 200
    assert "ses seç" in resp.get_data(as_text=True).lower()
    assert load_channel(path).reel is None
