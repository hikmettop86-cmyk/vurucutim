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
        })


def _make_news_channel(cfg_dir):
    from short_bot.config import ChannelConfig, save_channel
    cfg = ChannelConfig(
        slug="haber", name="Haber", keywords=["x"], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 8 * * *", duration_s=6, min_score=6.0, max_candidates_per_run=10,
        template="stat-hero", colors={"primary": "#000", "accent": "#fff",
        "bg_gradient": ["#000", "#111"]}, handle="@haber", output_dir="output/haber",
        enabled=True,        language="tr", dna=None, content_source="rss")
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
    # varyasyon/etkileşim + youtube form adları (beğeni/abone çipi alanı KALKTI)
    assert 'name="reel_cta_enabled"' not in body
    assert 'name="reel_comment_question"' in body
    assert 'name="reel_hook_angle_vary"' in body
    assert 'name="yt_privacy_status"' in body
    # niş bulucu + önizleme
    assert "reelPickNiche" in body
    assert 'id="niche-results"' in body


def test_edit_reel_post_preserves_dna_updates_reel(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    from short_bot.config import load_channel
    before = load_channel(cfg_dir / "channels" / "reel-kanal.yaml")
    r = c.post("/channels/reel-kanal/edit-reel", data={
        "reel_enabled": "on", "reel_voice_id": "NEWVOICE123",
        "reel_highlight_color": "#ff0000", "reel_cut_pacing": "fast",
        "reel_music_mood": "calm", "reel_layout": "classic",
        "reel_target_min": "20", "reel_target_max": "40",
        "generator_topic": "yeni konu tohumu en az on karakter",
        "schedule_cron": "0 9 * * *", "handle": "@yeni", "language": "en",
        "enabled": "1",
    })
    assert r.status_code in (200, 302)
    after = load_channel(cfg_dir / "channels" / "reel-kanal.yaml")
    # reel güncellendi
    assert after.reel.voice_id == "NEWVOICE123"
    assert after.reel.highlight_color == "#ff0000"
    assert after.reel.cut_pacing == "fast"
    assert after.generator.topic.startswith("yeni konu")
    assert after.schedule_cron == "0 9 * * *"
    assert after.language == "en"
    # DNA/arketip/renk KORUNDU (reel-güvenli)
    assert after.dna is not None
    assert after.dna.palette.header_top_color == before.dna.palette.header_top_color
    assert after.template == before.template
    assert after.colors == before.colors


def test_edit_reel_post_empty_voice_no_save(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    from short_bot.config import load_channel
    before_topic = load_channel(cfg_dir / "channels" / "reel-kanal.yaml").generator.topic
    r = c.post("/channels/reel-kanal/edit-reel", data={
        "reel_enabled": "on", "reel_voice_id": "",
        "generator_topic": "bambaska bir konu on karakterden fazla",
    })
    assert r.status_code in (200, 302)
    after = load_channel(cfg_dir / "channels" / "reel-kanal.yaml")
    assert after.generator.topic == before_topic  # kaydedilmedi


def test_reel_card_edit_link_goes_to_edit_reel(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    body = c.get("/channels").data.decode("utf-8")
    assert "/channels/reel-kanal/edit-reel" in body


def test_edit_reel_youtube_connect_ui_present(tmp_path):
    """Reel edit YouTube sekmesi gerçek bağlama yerini içermeli:
    client_secrets yükleme + connect/disconnect gizli formları."""
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    body = c.get("/channels/reel-kanal/edit-reel").data.decode("utf-8")
    assert 'id="yt-connect-form"' in body
    assert "/channels/reel-kanal/youtube/connect" in body
    assert "/channels/reel-kanal/youtube/upload-secrets" in body
    assert 'name="client_secrets"' in body


def test_edit_reel_post_preserves_music_volume_and_fuzzy(tmp_path):
    """Reel-güvenli save, formda olmayan nested alanları (music_volume,
    generator.fuzzy_threshold) sıfırlamamalı (review Important #1)."""
    from dataclasses import replace
    from short_bot.config import load_channel, save_channel
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    p = cfg_dir / "channels" / "reel-kanal.yaml"
    cfg = load_channel(p)
    cfg = replace(
        cfg,
        reel=cfg.reel.model_copy(update={"music_volume": 0.30}),
        generator=replace(cfg.generator, fuzzy_threshold=77.0),
    )
    save_channel(p, cfg)
    c.post("/channels/reel-kanal/edit-reel", data={
        "reel_enabled": "on", "reel_voice_id": "V", "reel_highlight_color": "#111111",
        "generator_topic": cfg.generator.topic,
    })
    after = load_channel(p)
    assert after.reel.music_volume == 0.30
    assert after.generator.fuzzy_threshold == 77.0


def test_post_edit_on_reel_channel_redirects_to_edit_reel(tmp_path):
    """Bayat /edit POST'u reel kanalda reel-güvenli sayfaya yönlenir (savunma)."""
    c, cfg_dir = _client(tmp_path)
    _make_reel_channel(c, cfg_dir)
    r = c.post("/channels/reel-kanal/edit", data={"schedule_cron": "0 5 * * *"})
    assert r.status_code == 302
    assert "/channels/reel-kanal/edit-reel" in r.headers["Location"]
