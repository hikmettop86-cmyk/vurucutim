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


def test_reel_post_empty_voice_no_channel(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        r = c.post("/channels/new-reel", data={
            "name": "Sessiz Kanal", "language": "tr",
            "topic": "uzay ve gezegenler hakkında ilginç bilgiler",
            "voice_id": "",
        })
    assert r.status_code in (200, 302)
    assert not (tmp_path / "config" / "channels" / "sessiz-kanal.yaml").exists()


def test_reel_post_short_topic_no_channel(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        r = c.post("/channels/new-reel", data={
            "name": "Kisa Konu", "language": "tr",
            "topic": "uzay",  # < 10 karakter
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
        })
    assert r.status_code in (200, 302)
    assert not (tmp_path / "config" / "channels" / "kisa-konu.yaml").exists()


def test_reel_post_slug_collision_gets_suffix(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        data = {
            "name": "Balina Dünyası", "language": "tr",
            "topic": "balinalar ve deniz memelileri hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
        }
        c.post("/channels/new-reel", data=dict(data))
        c.post("/channels/new-reel", data=dict(data))
    ch = tmp_path / "config" / "channels"
    assert (ch / "balina-dunyasi.yaml").exists()
    assert (ch / "balina-dunyasi-2.yaml").exists()


def test_reel_post_produce_now_launches_pipeline(tmp_path):
    c = _client(tmp_path)
    calls = []
    def _fake_launch(**kwargs):
        calls.append(kwargs)
        return None
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()), \
         patch("short_bot.web.routes.reel_new.launch_pipeline", _fake_launch):
        c.post("/channels/new-reel", data={
            "name": "Hemen Üret", "language": "tr",
            "topic": "bilim ve doğa hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
            "produce_now": "1",
        })
    assert len(calls) == 1
    assert calls[0]["channel"].slug == "hemen-uret"
    assert calls[0]["trigger"] == "manual"


def test_reel_post_no_produce_now_does_not_launch(tmp_path):
    c = _client(tmp_path)
    calls = []
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()), \
         patch("short_bot.web.routes.reel_new.launch_pipeline",
               lambda **k: calls.append(k)):
        c.post("/channels/new-reel", data={
            "name": "Sonra Üret", "language": "tr",
            "topic": "tarih hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
            "produce_now": "0",
        })
    assert calls == []


def test_channel_list_has_reel_button(tmp_path):
    c = _client(tmp_path)
    r = c.get("/channels")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "/channels/new-reel" in body
    assert "Reel" in body


def test_channel_list_shows_reel_badge(tmp_path):
    c = _client(tmp_path)
    # önce reel kanalı oluştur
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        c.post("/channels/new-reel", data={
            "name": "Reel Kanal", "language": "tr",
            "topic": "uzay ve gezegenler hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
        })
    r = c.get("/channels")
    body = r.data.decode("utf-8")
    assert "🎬" in body
