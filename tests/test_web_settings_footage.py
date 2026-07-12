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
