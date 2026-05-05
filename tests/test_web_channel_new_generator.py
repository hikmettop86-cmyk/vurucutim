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


def test_new_channel_form_has_content_source_radio(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/channels/new")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'name="content_source"' in body
    assert 'value="rss"' in body
    assert 'value="generator"' in body


def test_new_channel_form_has_generator_topic_field(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/channels/new")
    body = r.data.decode("utf-8")
    assert 'name="generator_topic"' in body
