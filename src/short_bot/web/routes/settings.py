"""Settings page: view + edit settings.yaml + write Pexels API key to data/secrets.yaml."""
import json
import logging
from pathlib import Path

import yaml
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from short_bot.config import load_settings

bp = Blueprint("settings", __name__)
_LOG = logging.getLogger(__name__)


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


def _load_catalog() -> dict:
    """config/openrouter_models.json'u yükle (proje kökü). Bulunamazsa boş."""
    candidates = [
        Path("config/openrouter_models.json"),
        current_app.config["SHORTBOT_CONFIG_DIR"] / "openrouter_models.json",
    ]
    for target in candidates:
        try:
            if target.exists():
                return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {"groups": []}


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
    openai_key_masked = _mask_key(secrets.get("openai_api_key", ""))
    youtube_key_masked = _mask_key(secrets.get("youtube_api_key", ""))
    openrouter_key_masked = _mask_key(secrets.get("openrouter_api_key", ""))
    return render_template("settings.html.j2", data=data, paths=paths,
                            pexels_key_masked=pexels_key_masked,
                            pexels_key_set=bool(secrets.get("pexels_api_key")),
                            openai_key_masked=openai_key_masked,
                            openai_key_set=bool(secrets.get("openai_api_key")),
                            youtube_key_masked=youtube_key_masked,
                            youtube_key_set=bool(secrets.get("youtube_api_key")),
                            ai_backend=data.get("ai_backend", "claude_cli"),
                            openrouter_models=data.get("openrouter_models", {}) or {},
                            openrouter_key_masked=openrouter_key_masked,
                            openrouter_key_set=bool(secrets.get("openrouter_api_key")),
                            openrouter_catalog=_load_catalog())


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
    models["script"]  = request.form.get("model_script", models.get("script"))
    data["claude_models"] = models

    # AI backend seçimi
    data["ai_backend"] = request.form.get("ai_backend", data.get("ai_backend", "claude_cli"))

    # OpenRouter rol modelleri ("__custom__" → serbest metin alanı)
    def _or_model(role: str) -> str:
        choice = request.form.get(f"or_model_{role}", "")
        if choice == "__custom__":
            return request.form.get(f"or_model_{role}_custom", "").strip()
        return choice
    or_models = data.get("openrouter_models", {}) or {}
    for role in ("dna", "default", "script"):
        val = _or_model(role)
        if val:
            or_models[role] = val
    if or_models:
        data["openrouter_models"] = or_models

    # Trends block
    trends_data = data.get("trends", {}) or {}
    trends_data["enabled"] = (request.form.get("trends_enabled") == "1")
    try:
        trends_data["refresh_minutes"] = int(
            request.form.get("trends_refresh_minutes",
                             trends_data.get("refresh_minutes", 60))
        )
    except (TypeError, ValueError):
        pass
    try:
        trends_data["cache_max_age_minutes"] = float(
            request.form.get("trends_cache_max_age_minutes",
                             trends_data.get("cache_max_age_minutes", 90))
        )
    except (TypeError, ValueError):
        pass
    src_list: list[str] = []
    if request.form.get("trends_src_google_daily") == "1":
        src_list.append("google_daily")
    if request.form.get("trends_src_youtube") == "1":
        src_list.append("youtube")
    if src_list:
        trends_data["default_sources"] = src_list
    data["trends"] = trends_data

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

    # OpenAI key — separate file (used by Dynamic DNA feature for embeddings)
    new_openai_key = request.form.get("openai_api_key", "").strip()
    clear_openai = request.form.get("openai_api_key_clear") == "1"
    if new_openai_key:
        secrets["openai_api_key"] = new_openai_key
        _save_secrets(secrets)
    elif clear_openai:
        secrets.pop("openai_api_key", None)
        _save_secrets(secrets)

    # YouTube API key — separate file (used by trends/youtube_trending for
    # videos.list(chart=mostPopular); does NOT replace per-channel OAuth)
    new_yt_key = request.form.get("youtube_api_key", "").strip()
    clear_yt = request.form.get("youtube_api_key_clear") == "1"
    if new_yt_key:
        secrets["youtube_api_key"] = new_yt_key
        _save_secrets(secrets)
    elif clear_yt:
        secrets.pop("youtube_api_key", None)
        _save_secrets(secrets)

    # OpenRouter API key — separate file
    new_or_key = request.form.get("openrouter_api_key", "").strip()
    clear_or = request.form.get("openrouter_api_key_clear") == "1"
    if new_or_key:
        secrets["openrouter_api_key"] = new_or_key
        _save_secrets(secrets)
    elif clear_or:
        secrets.pop("openrouter_api_key", None)
        _save_secrets(secrets)

    # Reload in-memory Settings so trend boost / refresh cron / cache TTL
    # take effect on the next pipeline run without an app restart. host/port
    # still need restart (Flask server bind happens once at startup) — flash
    # message hints at this.
    try:
        new_settings = load_settings(path)
        current_app.config["SHORTBOT_SETTINGS"] = new_settings
        _LOG.info("[settings] reloaded in-memory SHORTBOT_SETTINGS")
        # Re-arm the trends refresh cron with the new interval, if scheduler is running
        sched = getattr(current_app, "scheduler", None)
        if sched is not None and sched.get_job("_trends_refresh") is not None:
            from apscheduler.triggers.interval import IntervalTrigger
            sched.reschedule_job(
                "_trends_refresh",
                trigger=IntervalTrigger(minutes=new_settings.trends.refresh_minutes),
            )
            _LOG.info(
                f"[settings] _trends_refresh cron re-armed: "
                f"every {new_settings.trends.refresh_minutes}m"
            )
    except Exception as e:  # noqa: BLE001 — never let reload break the save flow
        _LOG.warning(f"[settings] in-memory reload failed: {e}")

    flash("Ayarlar kaydedildi. (host/port değişikliği için restart gerekir; "
          "diğer ayarlar anında aktif olur.)", "success")
    return redirect(url_for("settings.view"))
