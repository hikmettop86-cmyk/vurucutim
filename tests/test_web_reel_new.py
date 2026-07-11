from unittest.mock import patch

from short_bot.web import create_app
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec


def _client(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text("""\
ffmpeg_path: ffmpeg
claude_cli_path: claude
playwright_browser: chromium
web: {host: 127.0.0.1, port: 5005}
fuzzy_dedup_threshold: 0.85
log_level: INFO
claude_models: {dna: opus, default: haiku}
""", encoding="utf-8")
    app = create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                     templates_dir=tmp_path / "templates",
                     music_root=tmp_path, cache_dir=tmp_path,
                     lock_dir=tmp_path, logs_dir=tmp_path,
                     output_root=tmp_path, scheduler=False)
    return app.test_client()


def _fake_dna():
    return DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )


def test_reel_wizard_get_renders_key_fields(tmp_path):
    c = _client(tmp_path)
    r = c.get("/channels/new-reel")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'action="/channels/new-reel"' in body
    assert 'name="topic"' in body
    assert 'name="voice_id"' in body
    assert 'name="name"' in body
    assert 'name="variation_on"' in body
    assert 'name="cta_enabled"' in body
    assert 'name="produce_now"' in body
    # niş çipleri
    assert "Balinalar" in body
    assert "Uzay" in body


def test_reel_post_writes_channel_yaml(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        r = c.post("/channels/new-reel", data={
            "name": "Evrenin Sırları", "language": "tr",
            "topic": "uzay, gezegenler ve kara delikler hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
            "cut_pacing": "auto", "music_mood": "upbeat",
            "variation_on": "on", "cta_enabled": "on",
            "comment_question": "on",
            "produce_now": "0",
        })
    assert r.status_code in (200, 302)
    yaml_path = tmp_path / "config" / "channels" / "evrenin-sirlari.yaml"
    assert yaml_path.exists()
    contents = yaml_path.read_text(encoding="utf-8")
    assert "content_source: generator" in contents
    assert "generator:" in contents
    assert "kara delikler" in contents
    assert "reel:" in contents
    assert "enabled: true" in contents
    assert "Q2IX97JeHBY3vNGzgM5s" in contents
    assert "#38bdf8" in contents


def test_reel_post_variation_off_sets_vary_false(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        c.post("/channels/new-reel", data={
            "name": "Sakin Kanal", "language": "tr",
            "topic": "doğa ve vahşi yaşam hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
            # variation_on / cta_enabled / comment_question GÖNDERİLMEDİ → kapalı
            "produce_now": "0",
        })
    from short_bot.config import load_channel
    cfg = load_channel(tmp_path / "config" / "channels" / "sakin-kanal.yaml")
    assert cfg.reel.hook_angle_vary is False
    assert cfg.reel.accent_vary is False
    assert cfg.reel.transition_vary is False
    assert cfg.reel.cta_enabled is False
    assert cfg.reel.comment_question is False
