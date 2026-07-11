import re
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
    return app.test_client(), cfg_dir


def _fake_dna():
    return DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"],
                           header_top_color="#abcdef", header_bottom_color="#123456"),
        fonts=DnaFonts(), tone=DnaTone(voice="x", style="y"), persona_summary="x")


def _make_reel_channel(c, cfg_dir, slug_name="Reel Kanal"):
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        c.post("/channels/new-reel", data={
            "name": slug_name, "language": "tr",
            "topic": "uzay ve gezegenler hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s", "highlight_color": "#38bdf8",
            "cta_enabled": "on",
        })


def _make_news_channel(cfg_dir):
    from short_bot.config import ChannelConfig, save_channel
    cfg = ChannelConfig(
        slug="haber", name="Haber", keywords=["x"], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 8 * * *", duration_s=6, min_score=6.0, max_candidates_per_run=10,
        template="stat-hero", colors={"primary": "#000", "accent": "#fff",
        "bg_gradient": ["#000", "#111"]}, handle="@haber", output_dir="output/haber",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[], cta_duration_s=0,
        cta_show_handle=False, language="tr", dna=None, content_source="rss")
    save_channel(cfg_dir / "channels" / "haber.yaml", cfg)


def test_edit_reel_get_renders_reel_fields(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    r = c.get("/channels/reel-kanal/edit-reel")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'name="reel_voice_id"' in body
    assert 'name="reel_highlight_color"' in body
    assert 'name="generator_topic"' in body
    assert "AI Niş Bulucu" in body
    # haber/DNA/RSS alanları YOK
    assert 'name="dna_archetype"' not in body
    assert 'name="tb_enabled"' not in body


def test_edit_reel_get_non_reel_redirects_to_edit(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_news_channel(cfg_dir)
    r = c.get("/channels/haber/edit-reel")
    assert r.status_code == 302
    assert "/channels/haber/edit" in r.headers["Location"]
    assert "/edit-reel" not in r.headers["Location"]


def test_old_edit_reel_channel_redirects_to_edit_reel(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    r = c.get("/channels/reel-kanal/edit")
    assert r.status_code == 302
    assert "/channels/reel-kanal/edit-reel" in r.headers["Location"]


def test_edit_reel_full_page_tabs_and_values(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    body = c.get("/channels/reel-kanal/edit-reel").data.decode("utf-8")
    # 4 sekme
    for lbl in ("Kimlik", "Konu", "Format", "Varyasyon", "Abone", "YouTube"):
        assert lbl in body
    # mevcut değerler dolu
    assert "Q2IX97JeHBY3vNGzgM5s" in body     # reel_voice_id
    assert "#38bdf8" in body                   # reel_highlight_color
    assert "uzay ve gezegenler" in body        # generator_topic
    # paylaşılan alanlar
    assert 'name="schedule_cron"' in body
    assert 'name="handle"' in body
    assert 'name="language"' in body
    # varyasyon/abone + youtube form adları
    assert 'name="reel_cta_enabled"' in body
    assert 'name="reel_hook_angle_vary"' in body
    assert 'name="yt_privacy_status"' in body
    # niş bulucu + önizleme
    assert "reelPickNiche" in body
    assert 'id="niche-results"' in body
