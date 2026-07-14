"""short-bot web panel: Flask app factory + scheduler boot.

Usage:
    from short_bot.web import create_app
    app = create_app(config_dir=Path("config"), db_path=Path("data/short_bot.sqlite"))
    app.run(host="127.0.0.1", port=5005)
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from short_bot.config import load_settings
from short_bot.db import cleanup_zombie_runs, init_db
from short_bot.web.extensions import db


def create_app(
    *,
    config_dir: Path | str = "config",
    db_path: Path | str = "data/short_bot.sqlite",
    templates_dir: Path | str = "templates",
    music_root: Path | str = "assets/music",
    cache_dir: Path | str = "data/cache",
    lock_dir: Path | str = "data/locks",
    logs_dir: Path | str = "logs/runs",
    output_root: Path | str = "output",
    secrets_path: Path | str | None = None,
    scheduler: bool = True,
) -> Flask:
    """Construct the Flask app. `scheduler=False` for tests."""
    # Allow Electron / installer to override paths via env vars.
    # Set BEFORE any Path() normalization so overrides win over defaults.
    # NOTE: SHORT_BOT_DATA_DIR shadows the db_path/cache_dir/lock_dir arguments
    # if set — explicit args passed by callers are ignored. Empty string is rejected.
    config_dir = os.environ.get("SHORT_BOT_CONFIG_DIR", config_dir)
    _data_override = os.environ.get("SHORT_BOT_DATA_DIR")
    if _data_override is not None and not _data_override.strip():
        raise ValueError("SHORT_BOT_DATA_DIR must be non-empty if set")
    if _data_override:
        db_path = Path(_data_override) / "short_bot.sqlite"
        cache_dir = Path(_data_override) / "cache"
        lock_dir = Path(_data_override) / "locks"
    logs_dir = os.environ.get("SHORT_BOT_LOGS_DIR", logs_dir)
    output_root = os.environ.get("SHORT_BOT_OUTPUT_ROOT", output_root)

    config_dir = Path(config_dir)
    db_path = Path(db_path).resolve()    # absolute, avoids cwd surprises

    # Ensure schema exists (Phase 1+2 init_db is idempotent + adds pragmas)
    eng = init_db(db_path)
    # Bir önceki çökme/yeniden başlatmadan kalan enkazı topla.
    #
    # Panel yeniden başlatılınca UÇUŞTAKİ ÜRETİM ÖLÜR (thread, sürecin içinde). Geriye
    # 'running' bir koşu, 'producing'de donmuş bir otomasyon slotu ve sahipsiz bir kilit
    # kalır. Slot geri alınmazsa otomasyon onu bir daha ele almaz — günün videosu
    # sessizce yok olur (2026-07-14'te tam bu yaşandı).
    from short_bot.db import reclaim_producing_slots
    _geri = reclaim_producing_slots(eng)
    if _geri:
        import logging
        logging.getLogger("short_bot.web").warning(
            f"{_geri} otomasyon slotu 'producing'de öksüz kalmıştı → 'planned'a geri "
            f"alındı (panel yeniden başlatılırken üretim ölmüş).")
    n = cleanup_zombie_runs(eng, Path(lock_dir), age_minutes=60)
    if n:
        import logging
        logging.getLogger("short_bot.web").warning(
            "startup: cleaned %d zombie run(s)", n
        )

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    # Use POSIX path for SQLite URI: avoids backslash mangling on Windows
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.as_posix()}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "dev-key-change-me"   # dev only; localhost-only

    # Stash paths for blueprints
    app.config["SHORTBOT_CONFIG_DIR"] = config_dir
    app.config["SHORTBOT_DB_PATH"] = db_path
    app.config["SHORTBOT_TEMPLATES_DIR"] = Path(templates_dir)
    app.config["SHORTBOT_MUSIC_ROOT"] = Path(music_root)
    app.config["SHORTBOT_CACHE_DIR"] = Path(cache_dir)
    app.config["SHORTBOT_LOCK_DIR"] = Path(lock_dir)
    app.config["SHORTBOT_LOGS_DIR"] = Path(logs_dir)
    # Resolve to absolute — Flask's send_from_directory with a relative
    # `directory` looks under app.root_path (src/short_bot/web), not cwd,
    # which breaks /output/<file> with 404.
    app.config["SHORTBOT_OUTPUT_ROOT"] = Path(output_root).resolve()
    app.config["SHORTBOT_YT_CREDS_DIR"] = (
        db_path.parent / "youtube_credentials"
    ).resolve()
    app.config["SHORTBOT_SECRETS_PATH"] = (
        Path(secrets_path) if secrets_path is not None else Path("data") / "secrets.yaml"
    )
    app.config["SHORTBOT_SETTINGS"] = load_settings(config_dir / "settings.yaml")

    # ÜRETİLEN dil paketleri kullanıcının yazılabilir dizinine gider. Kodla gelenler
    # (tr, en) src/short_bot/langpacks/ altında; paketlenmiş Electron uygulamasında
    # kurulum dizini salt-okunur olabilir ve üretilenlerin bir yere yazılması gerekir.
    from short_bot.lang_pack import set_user_dir
    _langpacks = config_dir / "langpacks"
    _langpacks.mkdir(parents=True, exist_ok=True)
    set_user_dir(_langpacks)

    db.init_app(app)

    # JSON'da Türkçe karakterleri KAÇIRMA. Varsayılan ensure_ascii=True, "yayınlanacak"
    # ifadesini "yayınlanacak" yapıyor. Tarayıcı çözüyor ama HTML kaynağı okunmaz
    # hâle geliyor (|tojson ile yazılan onay metinleri, JSON yanıtları). UTF-8 zaten
    # her yerde; kaçırmanın hiçbir faydası yok.
    app.json.ensure_ascii = False

    # Register Jinja2 filters
    from short_bot.web.cron_describe import cron_human
    app.jinja_env.filters["cron_human"] = cron_human
    # Jinja'nın |upper filtresi Unicode'un DİLDEN BAĞIMSIZ eşlemesini kullanır:
    # "Bilim" → "BILIM". Türkçede "i"nin büyüğü "İ"dir. Şablonlarda |tr_upper kullan.
    from short_bot.text_normalize import turkish_upper
    app.jinja_env.filters["tr_upper"] = turkish_upper

    # Register blueprints
    from short_bot.web.routes import register_blueprints
    register_blueprints(app)

    # Friendly error pages — default Flask 404/500 don't have a back button.
    import traceback as _tb
    from flask import render_template as _render

    @app.errorhandler(404)
    def _on_404(e):
        return _render("_error.html.j2", code=404,
                       message="Aradığınız sayfa bulunamadı.",
                       detail=str(e)), 404

    @app.errorhandler(500)
    def _on_500(e):
        # Capture the traceback so users can paste it into a bug report.
        tb = _tb.format_exc()
        return _render("_error.html.j2", code=500,
                       message="Sunucuda beklenmeyen bir hata oluştu.",
                       detail=tb), 500

    @app.errorhandler(Exception)
    def _on_unhandled(e):
        # Catch-all: anything not produced as a Werkzeug HTTPException
        # (which Flask routes to the 404/500 handlers above) lands here.
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        tb = _tb.format_exc()
        return _render("_error.html.j2", code=500,
                       message=f"Beklenmeyen hata: {type(e).__name__}",
                       detail=tb), 500

    # Inject running-run count into all templates for the nav status badge
    from short_bot.web.models import Run
    @app.context_processor
    def inject_status():
        try:
            running = Run.query.filter(Run.status.in_(["running"]) | Run.status.is_(None),
                                        Run.ended_at.is_(None)).count()
        except Exception:
            running = 0
        return {"system_running_count": running}

    # Serve mp4 files from output directory
    @app.route("/output/<path:filename>")
    def serve_output(filename):
        from flask import send_from_directory
        return send_from_directory(app.config["SHORTBOT_OUTPUT_ROOT"], filename)

    if scheduler:
        from short_bot.web.scheduler import init_scheduler
        init_scheduler(app)
        from short_bot.web.scheduler_stats import init_stats_scheduler
        init_stats_scheduler(app)

    return app
