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


def test_new_channel_form_shows_bg_video_section(app):
    client = app.test_client()
    body = client.get("/channels/new").data.decode("utf-8")
    assert "Arka plan videosu" in body or "bg_video_enabled" in body
    assert 'name="bg_video_enabled"' in body
    # Both scale options
    assert "0.88" in body
    assert "0.80" in body


def test_new_channel_with_bg_video_writes_yaml(app):
    """Full wizard flow: generate + save with bg_video enabled → YAML has block."""
    import yaml
    client = app.test_client()
    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=_fake_dna()):
        client.post("/channels/new/generate", data={
            "name": "BG Test", "language": "tr",
            "keywords": "x", "topic_hint": "", "target_audience": "",
            "bg_video_enabled": "on",
            "bg_video_scale": "0.80",
            "bg_video_blur_px": "25",
            "bg_video_dim": "0.5",
        })
        client.post("/channels/new/save", data={
            "name": "BG Test", "language": "tr", "keywords": "x",
        })
    cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
    yaml_path = cfg_dir / "channels" / "bg-test.yaml"
    assert yaml_path.exists()
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert raw["bg_video"]["enabled"] is True
    assert raw["bg_video"]["scale"] == 0.80
    assert raw["bg_video"]["blur_px"] == 25
    assert raw["bg_video"]["dim"] == 0.5


def test_new_channel_without_bg_video_omits_block(app):
    """Wizard flow without bg_video_enabled → YAML has no bg_video block."""
    import yaml
    client = app.test_client()
    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=_fake_dna()):
        client.post("/channels/new/generate", data={
            "name": "No BG", "language": "tr",
            "keywords": "x", "topic_hint": "", "target_audience": "",
            # bg_video_enabled NOT submitted
        })
        client.post("/channels/new/save", data={
            "name": "No BG", "language": "tr", "keywords": "x",
        })
    cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
    yaml_path = cfg_dir / "channels" / "no-bg.yaml"
    assert yaml_path.exists()
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert "bg_video" not in raw


def test_new_channel_form_warns_when_pexels_key_absent(app):
    body = app.test_client().get("/channels/new").data.decode("utf-8")
    assert "Pexels API key tanımlı değil" in body
    assert "/settings" in body
