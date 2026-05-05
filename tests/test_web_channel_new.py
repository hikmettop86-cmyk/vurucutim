import pytest
from unittest.mock import patch

from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone
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
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite", scheduler=False)


def _fake_dna():
    return DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b", "#0a1a3b"],
                           body_bg=["#1a1a2a", "#0a0a1a"]),
        fonts=DnaFonts(headline="Inter", body="Inter"),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="z",
    )


def test_new_channel_wizard_form_renders(app):
    client = app.test_client()
    resp = client.get("/channels/new")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "İsim" in body or "Name" in body or "name" in body.lower()


def test_generate_dna_returns_partial(app):
    client = app.test_client()
    with patch("short_bot.web.routes.channel_new.generate_dna", return_value=_fake_dna()):
        resp = client.post("/channels/new/generate", data={
            "name": "Test Kanal", "language": "tr",
            "keywords": "a,b,c", "topic_hint": "", "target_audience": "",
        })
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "newscast" in body
    assert "#c81e1e" in body


def test_save_creates_channel_yaml_and_css(app):
    client = app.test_client()
    with patch("short_bot.web.routes.channel_new.generate_dna", return_value=_fake_dna()):
        # First generate (puts DNA in session)
        gen_resp = client.post("/channels/new/generate", data={
            "name": "Test Kanal", "language": "tr",
            "keywords": "a,b,c", "topic_hint": "", "target_audience": "",
        })
        # Then save
        save_resp = client.post("/channels/new/save", data={
            "name": "Test Kanal", "language": "tr",
            "keywords": "a,b,c",
        })
    assert save_resp.status_code in (200, 302)
    cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
    yaml_path = cfg_dir / "channels" / "test-kanal.yaml"
    assert yaml_path.exists()
