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
