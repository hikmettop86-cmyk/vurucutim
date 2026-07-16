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
reel: {enabled: true, voice_id: elevenlabs_x}
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


def _form(**over):
    f = {"schedule_cron": "0 9 * * *", "duration_s": "6", "min_score": "7.0",
         "max_candidates_per_run": "3", "max_age_hours": "24", "handle": "@testreel",
         "enabled": "1", "cta_enabled": "0", "cta_text": "", "cta_duration_s": "0",
         "cta_show_handle": "0", "keywords": "x", "content_source": "generator",
         "reel_enabled": "on", "reel_voice_id": "elevenlabs_x"}
    f.update(over); return f


def test_edit_shows_subscribe_fields(app):
    # Reel kanalları artık reel-özel düzenleme sayfasını kullanır (/edit → /edit-reel).
    body = app.test_client().get("/channels/test-reel/edit-reel").data.decode("utf-8")
    assert 'name="reel_series_enabled"' in body
    assert 'name="reel_series_title"' in body
    assert 'name="reel_comment_question"' in body
    # Beğeni/abone çipi alanları KALKTI (2026-07-16, kullanıcı kararı)
    assert 'name="reel_cta_enabled"' not in body
    assert 'name="reel_cta_text_custom"' not in body


def test_post_sets_subscribe(app):
    path = _path(app)
    app.test_client().post("/channels/test-reel/edit-reel", data=_form(
        reel_series_enabled="on", reel_series_title="Doğanın Sırları",
        reel_comment_question="on"))
    cfg = load_channel(path)
    assert cfg.reel.series_enabled is True
    assert cfg.reel.series_title == "Doğanın Sırları"
    assert cfg.reel.comment_question is True
    assert not hasattr(cfg.reel, "cta_enabled")   # alan tamamen kalktı
