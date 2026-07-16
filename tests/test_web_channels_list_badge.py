import pytest

from short_bot.config import ChannelConfig, GeneratorConfig, save_channel
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.web import create_app


def _seed_two_channels(tmp_path):
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
    rss_cfg = ChannelConfig(
        slug="haber", name="Haber", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=6.0,
        max_candidates_per_run=5, template="newscast",
        colors={"primary": "#000", "accent": "#111", "bg_gradient": ["#000", "#111"]},
        handle="@h", output_dir="output/h",
        enabled=True,        language="tr", dna=None, script_model=None,
        content_source="rss", generator=None,
    )
    gen_cfg = ChannelConfig(
        slug="sevgi", name="Sevgi", keywords=[], rss_locale="hl=tr",
        schedule_cron="*", duration_s=7, min_score=0.0,
        max_candidates_per_run=1, template="stat-hero",
        colors={"primary": "#000", "accent": "#fff", "bg_gradient": ["#000", "#111"]},
        handle="@s", output_dir="output/s",
        enabled=True,        language="tr", dna=dna, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(topic="Sevgi sözleri üretiyoruz."),
    )
    save_channel(cfg_dir / "channels" / "haber.yaml", rss_cfg)
    save_channel(cfg_dir / "channels" / "sevgi.yaml", gen_cfg)

    return create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "templates",
                      music_root=tmp_path, cache_dir=tmp_path,
                      lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, scheduler=False)


def test_channels_list_shows_badges_for_each_type(tmp_path):
    app = _seed_two_channels(tmp_path)
    r = app.test_client().get("/channels")
    body = r.data.decode("utf-8")
    # Both badges present somewhere in the list
    assert "📰" in body
    assert "✨" in body
