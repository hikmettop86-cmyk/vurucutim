from short_bot.web import create_app


def test_create_app_returns_flask(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "x.sqlite"
    app = create_app(config_dir=cfg_dir, db_path=db_path, scheduler=False)
    assert app is not None
    # URI is normalized to absolute POSIX path (Windows-safe)
    assert app.config["SQLALCHEMY_DATABASE_URI"] == f"sqlite:///{db_path.resolve().as_posix()}"


def test_app_has_blueprints(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    app = create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite", scheduler=False)
    expected = {"dashboard", "shorts", "feeds", "channels", "channel_new",
                "channel_edit", "preview", "logs"}
    assert expected <= set(app.blueprints.keys())
    # RSS görüntüleyici / Trendler / İçgörüler SAYFALARI kaldırıldı (kullanılmıyordu).
    # Hesap tarafı duruyor: trend_boost skorlaması ve generator'a giren
    # channel_insights scheduler cron'larından beslenir, panel sayfasına bağlı değil.
    assert {"rss", "trends", "insights"}.isdisjoint(set(app.blueprints.keys()))


def test_root_route_returns_200(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    app = create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite", scheduler=False)
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"vurucu" in resp.data.lower()
