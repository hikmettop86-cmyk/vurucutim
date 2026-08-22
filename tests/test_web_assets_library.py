"""Panel: Ayarlar → Varlık kütüphanesi (envanter + arka plan kurulum düğmesi)."""
from short_bot.web import create_app


def _client(tmp_path, music_root=None):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\nai_backend: openrouter\n",
        encoding="utf-8")
    app = create_app(config_dir=cfg, db_path=tmp_path/"db.sqlite",
                     templates_dir=tmp_path/"t",
                     music_root=music_root or (tmp_path / "assets" / "music"),
                     cache_dir=tmp_path, lock_dir=tmp_path, logs_dir=tmp_path,
                     output_root=tmp_path, secrets_path=tmp_path/"secrets.yaml",
                     scheduler=False)
    return app


def test_settings_shows_library_inventory(tmp_path):
    """Envanter klasörleri TARAYARAK kurulur — manifest gerekmez."""
    root = tmp_path / "assets"
    for cat, n in (("whoosh", 3), ("impact", 2)):
        d = root / "sfx" / cat; d.mkdir(parents=True)
        for i in range(n):
            (d / f"{i}.mp3").write_bytes(b"x")
    (root / "music" / "tense").mkdir(parents=True)
    (root / "music" / "tense" / "a.mp3").write_bytes(b"x")

    body = _client(tmp_path).test_client().get("/settings").data.decode("utf-8")
    assert "Varlık kütüphanesi" in body
    assert "5 SFX, 1 müzik" in body          # 3 whoosh + 2 impact
    assert "whoosh · 3" in body and "impact · 2" in body
    assert "tense · 1" in body


def test_empty_library_still_renders(tmp_path):
    """Kütüphane hiç kurulmamışsa ayarlar sayfası ÇÖKMEZ."""
    body = _client(tmp_path).test_client().get("/settings").data.decode("utf-8")
    assert "0 SFX, 0 müzik" in body
    assert "Kütüphaneyi Kur/Genişlet" in body


def test_build_button_launches_background_job(tmp_path, monkeypatch):
    import short_bot.web.routes.settings as st

    seen = {}
    monkeypatch.setattr(st, "_launch_library_build",
                        lambda root, per_sfx, per_music: seen.update(
                            root=root, per_sfx=per_sfx, per_music=per_music))
    app = _client(tmp_path)
    r = app.test_client().post("/settings/assets/build",
                               data={"per_sfx": "20", "per_music": "5"})
    assert r.status_code == 302                     # redirect → ayarlar
    assert seen["per_sfx"] == 20 and seen["per_music"] == 5
    # Kök = music_root'un ÜST klasörü (sfx/ ve music/ yan yana durur)
    assert seen["root"].name == "assets"


def test_build_clamps_absurd_counts(tmp_path, monkeypatch):
    import short_bot.web.routes.settings as st
    seen = {}
    monkeypatch.setattr(st, "_launch_library_build",
                        lambda root, per_sfx, per_music: seen.update(
                            per_sfx=per_sfx, per_music=per_music))
    _client(tmp_path).test_client().post("/settings/assets/build",
                                         data={"per_sfx": "9999", "per_music": "0"})
    assert seen["per_sfx"] == 40 and seen["per_music"] == 1


def test_concurrent_build_is_refused(tmp_path, monkeypatch):
    import short_bot.web.routes.settings as st
    monkeypatch.setitem(st._LIB_BUILD, "running", True)
    calls = []
    monkeypatch.setattr(st, "_launch_library_build",
                        lambda *a, **kw: calls.append(1))
    r = _client(tmp_path).test_client().post("/settings/assets/build", data={})
    assert r.status_code == 302 and calls == []      # ikinci kurulum başlatılmaz
