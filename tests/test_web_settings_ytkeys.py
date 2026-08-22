import yaml

from short_bot.web import create_app


def _client(tmp_path):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\nai_backend: openrouter\n",
        encoding="utf-8")
    app = create_app(config_dir=cfg, db_path=tmp_path / "db.sqlite",
                     templates_dir=tmp_path / "t", music_root=tmp_path,
                     cache_dir=tmp_path, lock_dir=tmp_path, logs_dir=tmp_path,
                     output_root=tmp_path, secrets_path=tmp_path / "secrets.yaml",
                     scheduler=False)
    return app, tmp_path / "secrets.yaml"


def test_settings_get_has_multi_key_textarea(tmp_path):
    app, _ = _client(tmp_path)
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert 'name="youtube_api_keys"' in body
    assert "kota rotasyonu" in body.lower() or "Kota rotasyonu" in body


def test_settings_post_saves_multi_keys(tmp_path):
    app, secrets_path = _client(tmp_path)
    app.test_client().post("/settings", data={
        "youtube_api_keys": "AIzaKEY1\n AIzaKEY2 \nAIzaKEY1\n\n",   # dup + boşluk
    })
    secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert secrets["youtube_api_keys"] == ["AIzaKEY1", "AIzaKEY2"]
    # boş kaydet → liste silinir
    app.test_client().post("/settings", data={"youtube_api_keys": ""})
    secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert "youtube_api_keys" not in secrets


def test_settings_get_prefills_existing_keys(tmp_path):
    app, secrets_path = _client(tmp_path)
    secrets_path.write_text("youtube_api_keys: [K1, K2]\n", encoding="utf-8")
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "K1\nK2" in body
