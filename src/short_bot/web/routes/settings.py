"""Settings page: view + edit settings.yaml."""
from pathlib import Path

import yaml
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

bp = Blueprint("settings", __name__)


def _settings_path() -> Path:
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "settings.yaml"


@bp.route("/settings", methods=["GET"])
def view():
    data = yaml.safe_load(_settings_path().read_text(encoding="utf-8")) or {}
    paths = {
        "Config dir": str(current_app.config["SHORTBOT_CONFIG_DIR"]),
        "DB":         str(current_app.config["SHORTBOT_DB_PATH"]),
        "Templates":  str(current_app.config["SHORTBOT_TEMPLATES_DIR"]),
        "Music":      str(current_app.config["SHORTBOT_MUSIC_ROOT"]),
        "Cache":      str(current_app.config["SHORTBOT_CACHE_DIR"]),
        "Locks":      str(current_app.config["SHORTBOT_LOCK_DIR"]),
        "Logs":       str(current_app.config["SHORTBOT_LOGS_DIR"]),
        "Output":     str(current_app.config["SHORTBOT_OUTPUT_ROOT"]),
    }
    return render_template("settings.html.j2", data=data, paths=paths)


@bp.route("/settings", methods=["POST"])
def save():
    """Update editable settings.yaml fields. Restart needed for some to take effect."""
    path = _settings_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    data["ffmpeg_path"]      = request.form.get("ffmpeg_path", data.get("ffmpeg_path"))
    data["claude_cli_path"]  = request.form.get("claude_cli_path", data.get("claude_cli_path"))
    data["playwright_browser"] = request.form.get("playwright_browser",
                                                  data.get("playwright_browser"))
    try:
        data["fuzzy_dedup_threshold"] = float(request.form.get("fuzzy_dedup_threshold",
                                                                 data.get("fuzzy_dedup_threshold")))
    except (TypeError, ValueError):
        pass
    data["log_level"]        = request.form.get("log_level", data.get("log_level"))

    web = data.get("web", {})
    web["host"] = request.form.get("web_host", web.get("host"))
    try:
        web["port"] = int(request.form.get("web_port", web.get("port")))
    except (TypeError, ValueError):
        pass
    data["web"] = web

    models = data.get("claude_models", {})
    models["dna"]     = request.form.get("model_dna", models.get("dna"))
    models["default"] = request.form.get("model_default", models.get("default"))
    data["claude_models"] = models

    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    flash("Ayarlar kaydedildi. Bazı değişiklikler için panel yeniden başlatılmalı.", "success")
    return redirect(url_for("settings.view"))
