# tests/test_web_generator_test.py
from unittest.mock import patch

import pytest

from short_bot.config import ChannelConfig, GeneratorConfig, save_channel
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.generator import GeneratorResult
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
        archetype="stat-hero",
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
        max_candidates_per_run=1, template="stat-hero",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir="output/sevgi",
        enabled=True,        language="tr", dna=dna, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(topic="Sevgi sözleri üretiyoruz."),
    )
    save_channel(cfg_dir / "channels" / "sevgi.yaml", cfg)

    return create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "templates",
                      music_root=tmp_path, cache_dir=tmp_path,
                      lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, scheduler=False)


def _fake_result():
    return GeneratorResult(
        text="Aşk anlayışta başlar.",
        topic_tag="tanisma",
        script={
            "header_top": "AŞK", "header_bottom": "ÜZERİNE",
            "photo_overlay": "Sevgi",
            "body_paragraph": "Aşk anlayışta başlar. Bir bakış güzelliktir, anlayış sevdadır.",
            "highlights": [{"text": "anlayışta", "color": "yellow"}],
            "category": "ask", "mood": "neutral",
        },
        image_keywords=["couple silhouette", "sunset"],
    )


def test_generator_test_endpoint_returns_result(app):
    c = app.test_client()
    with patch("short_bot.web.routes.generator_test.generate_quote",
               return_value=_fake_result()):
        r = c.post("/channels/sevgi/generator-test")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Aşk anlayışta" in body
    assert "tanisma" in body


def test_generator_test_does_not_persist(app, tmp_path):
    c = app.test_client()
    with patch("short_bot.web.routes.generator_test.generate_quote",
               return_value=_fake_result()):
        c.post("/channels/sevgi/generator-test")
    # Verify nothing in generated_items
    from short_bot.db import init_db
    from short_bot.generated_db import generated_items
    from sqlalchemy import select
    eng = init_db(tmp_path / "db.sqlite")
    with eng.connect() as conn:
        rows = conn.execute(select(generated_items)).fetchall()
    eng.dispose()
    assert rows == []


def _openrouter_app(tmp_path):
    """App with ai_backend=openrouter + secrets file, generator channel 'sevgi'."""
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
ai_backend: openrouter
openrouter_models: {dna: or-opus, default: or-default, script: or-script}
""", encoding="utf-8")

    dna = DnaSpec(
        archetype="stat-hero",
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
        max_candidates_per_run=1, template="stat-hero",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir="output/sevgi",
        enabled=True,        language="tr", dna=dna, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(topic="Sevgi sözleri üretiyoruz."),
    )
    save_channel(cfg_dir / "channels" / "sevgi.yaml", cfg)

    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text("openrouter_api_key: sk-or-test123\n", encoding="utf-8")

    return create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "templates",
                      music_root=tmp_path, cache_dir=tmp_path,
                      lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, secrets_path=secrets_path,
                      scheduler=False)


def test_generator_test_uses_openrouter_backend_when_configured(tmp_path):
    """ai_backend=openrouter → generate_quote gets backend/api_key + openrouter model
    (NOT the channel.script_model precedence, which only applies in claude_cli mode)."""
    app = _openrouter_app(tmp_path)
    captured = {}

    def fake_generate(*, channel, dna, forbidden_texts, topic_distribution, **kw):
        captured.update(kw)
        return _fake_result()

    with patch("short_bot.web.routes.generator_test.generate_quote",
               side_effect=fake_generate):
        r = app.test_client().post("/channels/sevgi/generator-test")
    assert r.status_code == 200
    assert captured["backend"] == "openrouter"
    assert captured["api_key"] == "sk-or-test123"
    # openrouter mode: resolved model wins, channel.script_model ignored
    assert captured["model"] == "or-default"


def test_generator_test_keeps_script_model_in_claude_cli_mode(app):
    """claude_cli mode (default) must preserve channel.script_model precedence."""
    captured = {}

    def fake_generate(*, channel, dna, forbidden_texts, topic_distribution, **kw):
        captured.update(kw)
        return _fake_result()

    with patch("short_bot.web.routes.generator_test.generate_quote",
               side_effect=fake_generate):
        app.test_client().post("/channels/sevgi/generator-test")
    assert captured["backend"] == "claude_cli"
    # channel.script_model is "sonnet" → wins over claude_models.default
    assert captured["model"] == "sonnet"


def test_generator_test_400_on_rss_channel(app, tmp_path):
    """Test endpoint refuses non-generator channels."""
    cfg_dir = tmp_path / "config"
    rss_yaml = cfg_dir / "channels" / "haber.yaml"
    rss_yaml.write_text("""\
slug: haber
name: Haber
language: tr
keywords: [x]
schedule_cron: "0 9 * * *"
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors: {primary: "#000", accent: "#111", bg_gradient: ["#000", "#111"]}
handle: "@h"
output_dir: output/h
enabled: true
cta: {enabled: false, text: "", icons: [], duration_s: 0, show_handle: false}
""", encoding="utf-8")
    r = app.test_client().post("/channels/haber/generator-test")
    assert r.status_code == 400
