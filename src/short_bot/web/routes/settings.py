"""Settings page: view + edit settings.yaml + write Pexels API key to data/secrets.yaml."""
from pathlib import Path

import yaml
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

bp = Blueprint("settings", __name__)


def _settings_path() -> Path:
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "settings.yaml"


def _secrets_path() -> Path:
    return Path(current_app.config["SHORTBOT_SECRETS_PATH"])


def _load_secrets() -> dict:
    p = _secrets_path()
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _save_secrets(data: dict) -> None:
    p = _secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")


def _mask_key(key: str) -> str:
    if not key:
        return ""
    return "•" * 8 + (key[-4:] if len(key) >= 4 else "")


@bp.route("/settings", methods=["GET"])
def view():
    data = yaml.safe_load(_settings_path().read_text(encoding="utf-8")) or {}
    secrets = _load_secrets()
    paths = {
        "Config dir": str(current_app.config["SHORTBOT_CONFIG_DIR"]),
        "DB":         str(current_app.config["SHORTBOT_DB_PATH"]),
        "Templates":  str(current_app.config["SHORTBOT_TEMPLATES_DIR"]),
        "Music":      str(current_app.config["SHORTBOT_MUSIC_ROOT"]),
        "Cache":      str(current_app.config["SHORTBOT_CACHE_DIR"]),
        "Locks":      str(current_app.config["SHORTBOT_LOCK_DIR"]),
        "Logs":       str(current_app.config["SHORTBOT_LOGS_DIR"]),
        "Output":     str(current_app.config["SHORTBOT_OUTPUT_ROOT"]),
        "Secrets":    str(_secrets_path()),
    }
    pexels_key_masked = _mask_key(secrets.get("pexels_api_key", ""))
    return render_template("settings.html.j2", data=data, paths=paths,
                            pexels_key_masked=pexels_key_masked,
                            pexels_key_set=bool(secrets.get("pexels_api_key")))


@bp.route("/settings", methods=["POST"])
def save():
    """Update settings.yaml and (separately) data/secrets.yaml for Pexels key."""
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

    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")

    # Pexels key — separate file
    secrets = _load_secrets()
    new_key = request.form.get("pexels_api_key", "").strip()
    clear = request.form.get("pexels_api_key_clear") == "1"
    if new_key:
        secrets["pexels_api_key"] = new_key
        _save_secrets(secrets)
    elif clear:
        secrets.pop("pexels_api_key", None)
        _save_secrets(secrets)

    flash("Ayarlar kaydedildi. Bazı değişiklikler için panel yeniden başlatılmalı.", "success")
    return redirect(url_for("settings.view"))
