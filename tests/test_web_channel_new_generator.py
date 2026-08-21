from short_bot.web import create_app


def _client(tmp_path, monkeypatch):
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


def test_generator_kanali_DUZENLEME_sayfasindan_ayarlanir(tmp_path, monkeypatch):
    """Eski DNA sihirbazının /channels/new formu kalktı — kurulum artık format
    seçimi + sohbet.

    BİLİNEN BOŞLUK: düzenleme sayfasındaki içerik kaynağı listesinde
    rss/feed/trends var, `generator` YOK — yani mevcut generator kanalı
    düzenlenebilir ama bir kanalı generator'a ÇEVİRME yolu kalmadı.
    Ölçüldü (2026-08-21): canlıda generator kullanan kanal YOK (4 trends,
    1 curated, gerisi rss), o yüzden kapatılmadı. İhtiyaç doğarsa radio
    listesine eklenir."""
    c = _client(tmp_path, monkeypatch)
    yaml_metni = "\n".join([
        "slug: genk", "name: Gen", "handle: '@genk'", "keywords: [a]",
        "language: tr", "schedule_cron: '0 9 * * *'", "duration_s: 6",
        "min_score: 6.0", "max_candidates_per_run: 10", "template: newscast",
        "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}",
        "output_dir: out", "enabled: true",
        "content_source: generator",
        "generator: {topic: 'ilginc bilgiler hakkinda kisa videolar'}", ""])
    (tmp_path / "config" / "channels" / "genk.yaml").write_text(
        yaml_metni, encoding="utf-8")
    body = c.get("/channels/genk/edit").data.decode("utf-8")
    assert 'name="generator_topic"' in body
    assert "ilginc bilgiler" in body
    assert 'name="content_source"' in body


from unittest.mock import patch

from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec


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


def test_save_generator_channel_writes_yaml_with_generator_block(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=_fake_dna()), \
         patch("short_bot.web.routes.channel_new.smoke_render_dna",
               return_value=(True, "ok")):
        r1 = c.post("/channels/new/generate", data={
            "name": "Sevgi Sözleri", "language": "tr",
            "content_source": "generator",
            "generator_topic": "Sevgi ve aşk üzerine kısa, vurucu sözler",
        })
        assert r1.status_code == 200

        r2 = c.post("/channels/new/save", data={
            "name": "Sevgi Sözleri", "language": "tr",
            "content_source": "generator",
            "generator_topic": "Sevgi ve aşk üzerine kısa, vurucu sözler",
        })
    assert r2.status_code in (200, 302)

    yaml_path = (tmp_path / "config" / "channels" / "sevgi-sozleri.yaml")
    assert yaml_path.exists()
    contents = yaml_path.read_text(encoding="utf-8")
    assert "content_source: generator" in contents
    assert "generator:" in contents
    assert "Sevgi ve aşk" in contents


def test_save_rss_channel_unchanged_no_generator_block(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=_fake_dna()), \
         patch("short_bot.web.routes.channel_new.smoke_render_dna",
               return_value=(True, "ok")):
        c.post("/channels/new/generate", data={
            "name": "Haber", "language": "tr",
            "content_source": "rss",
            "keywords": "ekonomi, siyaset",
        })

        r2 = c.post("/channels/new/save", data={
            "name": "Haber", "language": "tr",
            "content_source": "rss",
            "keywords": "ekonomi, siyaset",
        })
    assert r2.status_code in (200, 302)
    yaml_path = tmp_path / "config" / "channels" / "haber.yaml"
    assert yaml_path.exists()
    contents = yaml_path.read_text(encoding="utf-8")
    assert "content_source" not in contents    # default not serialized
    assert "generator:" not in contents


def test_smoke_fail_blocks_channel_save(tmp_path, monkeypatch):
    """When smoke_render returns False, save() flashes error and skips YAML write."""
    c = _client(tmp_path, monkeypatch)
    fake_dna = _fake_dna()

    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=fake_dna), \
         patch("short_bot.web.routes.channel_new.smoke_render_dna",
               return_value=(False, "render exception: layout broke")):
        c.post("/channels/new/generate", data={
            "name": "Smoke Fail", "language": "tr",
            "content_source": "rss", "keywords": "x",
        })
        r = c.post("/channels/new/save", data={
            "name": "Smoke Fail", "language": "tr",
            "content_source": "rss", "keywords": "x",
        })

    # Save was skipped → no YAML file created
    assert not (tmp_path / "config" / "channels" / "smoke-fail.yaml").exists()
    # Should redirect back to wizard form (not edit page)
    assert r.status_code in (200, 302)


def test_smoke_pass_allows_channel_save(tmp_path, monkeypatch):
    """When smoke_render returns True, save() proceeds normally."""
    c = _client(tmp_path, monkeypatch)
    fake_dna = _fake_dna()

    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=fake_dna), \
         patch("short_bot.web.routes.channel_new.smoke_render_dna",
               return_value=(True, "ok")):
        c.post("/channels/new/generate", data={
            "name": "Smoke Pass", "language": "tr",
            "content_source": "rss", "keywords": "x",
        })
        c.post("/channels/new/save", data={
            "name": "Smoke Pass", "language": "tr",
            "content_source": "rss", "keywords": "x",
        })

    assert (tmp_path / "config" / "channels" / "smoke-pass.yaml").exists()
