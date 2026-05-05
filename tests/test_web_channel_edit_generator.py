import pytest
import yaml

from short_bot.config import ChannelConfig, GeneratorConfig, save_channel
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
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

    dna = DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )
    cfg = ChannelConfig(
        slug="sevgi", name="Sevgi", keywords=[], rss_locale="hl=tr",
        schedule_cron="0 9 * * *", duration_s=7, min_score=0.0,
        max_candidates_per_run=1, template="kinetic",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir="output/sevgi",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=dna, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(topic="Sevgi sözleri üretiyoruz."),
    )
    save_channel(cfg_dir / "channels" / "sevgi.yaml", cfg)

    return create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "templates",
                      music_root=tmp_path, cache_dir=tmp_path,
                      lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, scheduler=False)


def test_edit_page_shows_generator_topic_field(app):
    r = app.test_client().get("/channels/sevgi/edit")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'name="generator_topic"' in body
    assert "Sevgi sözleri üretiyoruz." in body


def test_edit_page_shows_test_uret_button_for_generator(app):
    r = app.test_client().get("/channels/sevgi/edit")
    body = r.data.decode("utf-8")
    assert "Test örnek" in body or "generator-test" in body


def test_edit_save_updates_generator_topic(app, tmp_path):
    c = app.test_client()
    r = c.post("/channels/sevgi/edit", data={
        "keywords": "",
        "schedule_cron": "0 9 * * *",
        "duration_s": "7", "min_score": "0",
        "max_candidates_per_run": "1",
        "handle": "@sevgi",
        "enabled": "1",
        "generator_topic": "GÜNCELLENDİ topic minimum on karakter.",
        "generator_forbidden_lookback": "75",
        "generator_max_retries": "5",
    })
    assert r.status_code in (200, 302)

    yaml_path = tmp_path / "config" / "channels" / "sevgi.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["generator"]["topic"].startswith("GÜNCELLENDİ")
    assert data["generator"]["forbidden_lookback"] == 75
    assert data["generator"]["max_retries"] == 5


def test_regenerate_dna_blocks_save_on_smoke_fail(app, tmp_path):
    """regenerate_dna must preserve old DNA when smoke_render returns False."""
    from unittest.mock import patch
    from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec

    c = app.test_client()
    new_dna = DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#abcabc", accent="#defdef",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="new", style="new"),
        persona_summary="new persona",
    )
    with patch("short_bot.web.routes.channel_edit.generate_dna",
               return_value=new_dna), \
         patch("short_bot.web.routes.channel_edit.smoke_render_dna",
               return_value=(False, "blank frame")):
        r = c.post("/channels/sevgi/regenerate-dna")

    assert r.status_code in (200, 302)

    # Verify old DNA preserved in YAML — persona_summary should still be "x"
    yaml_path = tmp_path / "config" / "channels" / "sevgi.yaml"
    yaml_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert yaml_data["dna"]["persona_summary"] == "x"
