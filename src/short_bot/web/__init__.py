"""short-bot web panel: Flask app factory + scheduler boot.

Usage:
    from short_bot.web import create_app
    app = create_app(config_dir=Path("config"), db_path=Path("data/short_bot.sqlite"))
    app.run(host="127.0.0.1", port=5005)
"""
from __future__ import annotations

from pathlib import Path

from flask import Flask

from short_bot.config import load_settings
from short_bot.db import init_db
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
    scheduler: bool = True,
) -> Flask:
    """Construct the Flask app. `scheduler=False` for tests."""
    config_dir = Path(config_dir)
    db_path = Path(db_path)

    # Ensure schema exists (Phase 1+2 init_db is idempotent + adds pragmas)
    init_db(db_path)

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
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
    app.config["SHORTBOT_OUTPUT_ROOT"] = Path(output_root)
    app.config["SHORTBOT_SETTINGS"] = load_settings(config_dir / "settings.yaml")

    db.init_app(app)

    # Register blueprints
    from short_bot.web.routes import register_blueprints
    register_blueprints(app)

    if scheduler:
        from short_bot.web.scheduler import init_scheduler
        init_scheduler(app)

    return app
