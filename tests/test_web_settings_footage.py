import yaml
from short_bot.web import create_app


def _client(tmp_path):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\nai_backend: openrouter\n", encoding="utf-8")
    app = create_app(config_dir=cfg, db_path=tmp_path/"db.sqlite", templates_dir=tmp_path/"t",
                     music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                     logs_dir=tmp_path, output_root=tmp_path,
                     secrets_path=tmp_path/"secrets.yaml", scheduler=False)
    return app, cfg


def test_settings_get_has_pixabay_and_footage(tmp_path):
    app, _ = _client(tmp_path)
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert 'name="pixabay_api_key"' in body
    assert "Footage" in body
    for s in ("pexels", "pixabay", "storyblocks"):
        assert f'value="{s}"' in body or f'name="footage_src_{s}"' in body


def test_settings_post_saves_pixabay_and_priority(tmp_path):
    app, cfg = _client(tmp_path)
    app.test_client().post("/settings", data={
        "pixabay_api_key": "PIXKEY123",
        "footage_src_pixabay": "1", "footage_src_pexels": "1",
        "footage_order": "pixabay,pexels",
    })
    secrets = yaml.safe_load((tmp_path/"secrets.yaml").read_text(encoding="utf-8"))
    assert secrets["pixabay_api_key"] == "PIXKEY123"
    data = yaml.safe_load((cfg/"settings.yaml").read_text(encoding="utf-8"))
    assert data["footage"]["priority"] == ["pixabay", "pexels"]


def test_settings_shows_storyblocks_status(tmp_path, monkeypatch):
    # Bağlantı durumunu deterministik sabitle (gerçek oturum dosyasına bağlı olmasın).
    import short_bot.web.routes.settings as st
    monkeypatch.setattr(st, "_storyblocks_connected", lambda: False)
    app, _ = _client(tmp_path)
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "Storyblocks" in body
    assert "/settings/storyblocks/connect" in body


def test_storyblocks_connect_triggers_login(tmp_path, monkeypatch):
    app, _ = _client(tmp_path)
    calls = []
    import short_bot.web.routes.settings as st
    # login'i sahtele (gerçek tarayıcı açılmasın)
    monkeypatch.setattr(st, "_launch_storyblocks_login", lambda path: calls.append(path))
    r = app.test_client().post("/settings/storyblocks/connect")
    assert r.status_code in (200, 302)
    assert len(calls) == 1


def test_storyblocks_disconnect_deletes(tmp_path, monkeypatch):
    app, _ = _client(tmp_path)
    import short_bot.web.routes.settings as st
    deleted = []
    monkeypatch.setattr(st, "_delete_storyblocks_session", lambda path: deleted.append(path))
    r = app.test_client().post("/settings/storyblocks/disconnect")
    assert r.status_code in (200, 302) and len(deleted) == 1


def test_settings_footage_canonical_order_with_real_values(tmp_path):
    """Gerçek template value=source-adı gönderir; hepsi seçili → kanonik sıra."""
    app, cfg = _client(tmp_path)
    app.test_client().post("/settings", data={
        "footage_src_storyblocks": "storyblocks",
        "footage_src_pixabay": "pixabay",
        "footage_src_pexels": "pexels",
    })
    data = yaml.safe_load((cfg / "settings.yaml").read_text(encoding="utf-8"))
    assert data["footage"]["priority"] == ["storyblocks", "pixabay", "pexels"]


def test_settings_footage_subset_and_order(tmp_path):
    # sadece storyblocks + pexels (value=adı) → [storyblocks, pexels] kanonik
    app, cfg = _client(tmp_path)
    app.test_client().post("/settings", data={
        "footage_src_storyblocks": "storyblocks", "footage_src_pexels": "pexels"})
    data = yaml.safe_load((cfg / "settings.yaml").read_text(encoding="utf-8"))
    assert data["footage"]["priority"] == ["storyblocks", "pexels"]


def test_settings_footage_none_defaults_pexels(tmp_path):
    app, cfg = _client(tmp_path)
    app.test_client().post("/settings", data={})   # hiç footage kutusu işaretli değil
    data = yaml.safe_load((cfg / "settings.yaml").read_text(encoding="utf-8"))
    assert data["footage"]["priority"] == ["pexels"]
