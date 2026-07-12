"""Settings page: view + edit settings.yaml + write Pexels API key to data/secrets.yaml."""
import logging
from pathlib import Path

import yaml
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from short_bot.config import load_settings
from short_bot.openrouter_catalog import get_catalog

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


def _storyblocks_session_path() -> Path:
    settings = current_app.config.get("SHORTBOT_SETTINGS")
    sp = getattr(settings, "storyblocks_session", None) or "data/storyblocks_session.json"
    return Path(sp)


def _storyblocks_connected() -> bool:
    """True if a saved Storyblocks session exists. Never raises (is_ready is defensive)."""
    try:
        from short_bot.storyblocks_browser import is_ready
        return is_ready(_storyblocks_session_path())
    except Exception:  # noqa: BLE001 — playwright/session missing → treat as disconnected
        return False


def _launch_storyblocks_login(session_path) -> None:
    """Open a headed browser on the user's desktop in a daemon thread.

    Runs in the background so the POST returns immediately (does NOT block).
    Tests monkeypatch this function so no real browser is ever opened."""
    import threading

    def _run():
        try:
            from short_bot.storyblocks_login import run_login
            run_login(str(session_path))
        except Exception as e:  # noqa: BLE001 — background thread must not crash the app
            _LOG.warning(f"[settings] storyblocks login failed: {e}")

    threading.Thread(target=_run, daemon=True).start()


def _delete_storyblocks_session(session_path) -> None:
    from short_bot.storyblocks_login import delete_session
    delete_session(str(session_path))


# --- Varlık kütüphanesi (SFX + müzik) ------------------------------------
# Kurulum ağdan indirir (dakikalar sürebilir) → arka plan thread'i, POST anında döner.
# Storyblocks-login deseninin aynısı: modül-düzeyi durum + daemon thread.
_LIB_BUILD: dict = {"running": False, "status": ""}


def _assets_root() -> Path:
    """SFX/müzik kökü: music_root'un üst klasörü (paketlenmiş uygulamada taşınır)."""
    return Path(current_app.config["SHORTBOT_MUSIC_ROOT"]).parent


def _library_inventory() -> dict:
    """Kütüphane envanteri: {"sfx": {kat: n}, "music": {mood: n}, "total_*": N}."""
    try:
        from short_bot.assets_library import load_library_index
        idx = load_library_index(_assets_root())
    except Exception as e:  # noqa: BLE001 — envanter ayarlar sayfasını düşürmesin
        _LOG.warning(f"[settings] varlık envanteri okunamadı: {e}")
        return {"sfx": {}, "music": {}, "total_sfx": 0, "total_music": 0}
    sfx = {k: len(v) for k, v in idx.get("sfx", {}).items()}
    music = {k: len(v) for k, v in idx.get("music", {}).items()}
    return {"sfx": sfx, "music": music,
            "total_sfx": sum(sfx.values()), "total_music": sum(music.values())}


def _launch_library_build(root, per_sfx: int, per_music: int) -> None:
    """Kütüphaneyi arka planda kur/genişlet. Testler bu fonksiyonu monkeypatch'ler."""
    import threading

    def _run():
        try:
            from short_bot.assets_library import build_library
            res = build_library(root, per_sfx=per_sfx, per_music=per_music,
                                progress=lambda m: _LIB_BUILD.update(status=m))
            _LIB_BUILD["status"] = (f"Tamamlandı: +{res['sfx']} SFX, "
                                    f"+{res['music']} müzik")
        except Exception as e:  # noqa: BLE001 — arka plan thread'i uygulamayı düşürmesin
            _LIB_BUILD["status"] = f"Hata: {e}"
            _LOG.warning(f"[settings] kütüphane kurulumu başarısız: {e}")
        finally:
            _LIB_BUILD["running"] = False

    _LIB_BUILD.update(running=True, status="Başlıyor…")
    threading.Thread(target=_run, daemon=True).start()


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
    pixabay_key_masked = _mask_key(secrets.get("pixabay_api_key", ""))
    openai_key_masked = _mask_key(secrets.get("openai_api_key", ""))
    youtube_key_masked = _mask_key(secrets.get("youtube_api_key", ""))
    openrouter_key_masked = _mask_key(secrets.get("openrouter_api_key", ""))
    ai33_key_masked = _mask_key(secrets.get("ai33_api_key", ""))
    cache_dir = current_app.config.get("SHORTBOT_CACHE_DIR") or Path("data")
    return render_template("settings.html.j2", data=data, paths=paths,
                            pexels_key_masked=pexels_key_masked,
                            pexels_key_set=bool(secrets.get("pexels_api_key")),
                            pixabay_key_masked=pixabay_key_masked,
                            pixabay_key_set=bool(secrets.get("pixabay_api_key")),
                            footage=data.get("footage", {}) or {},
                            storyblocks_connected=_storyblocks_connected(),
                            openai_key_masked=openai_key_masked,
                            openai_key_set=bool(secrets.get("openai_api_key")),
                            youtube_key_masked=youtube_key_masked,
                            youtube_key_set=bool(secrets.get("youtube_api_key")),
                            youtube_extra_keys="\n".join(
                                secrets.get("youtube_api_keys") or []),
                            ai33_key_masked=ai33_key_masked,
                            ai33_key_set=bool(secrets.get("ai33_api_key")),
                            ai_backend=data.get("ai_backend", "claude_cli"),
                            openrouter_models=data.get("openrouter_models", {}) or {},
                            openrouter_key_masked=openrouter_key_masked,
                            openrouter_key_set=bool(secrets.get("openrouter_api_key")),
                            openrouter_catalog=get_catalog(Path(cache_dir)),
                            asset_library=_library_inventory(),
                            library_building=_LIB_BUILD.get("running", False),
                            library_status=_LIB_BUILD.get("status", ""))


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
    for role in ("dna", "default", "script", "vision"):
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

    # Footage kaynak önceliği: seçili (checked) kaynaklar sabit kanonik sırada
    # (storyblocks → pixabay → pexels). Checkbox VARLIĞINA bakılır (value ne olursa
    # olsun) — böylece template value="pexels" ile de doğru çalışır. Hiçbiri seçili
    # değilse [pexels] varsayılan.
    _CANON = ("storyblocks", "pixabay", "pexels")
    ordered = [s for s in _CANON if request.form.get(f"footage_src_{s}")]
    if not ordered:
        ordered = ["pexels"]
    fdata = data.get("footage", {}) or {}
    fdata["priority"] = ordered
    data["footage"] = fdata

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

    # Pixabay key — separate file (footage kaynağı)
    new_pixabay_key = request.form.get("pixabay_api_key", "").strip()
    clear_pixabay = request.form.get("pixabay_api_key_clear") == "1"
    if new_pixabay_key:
        secrets["pixabay_api_key"] = new_pixabay_key
        _save_secrets(secrets)
    elif clear_pixabay:
        secrets.pop("pixabay_api_key", None)
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

    # Ek YouTube API anahtarları (çoklu — konu-bankası madencisi kota rotasyonu).
    # Textarea içeriği liste OLUR: her satır bir anahtar; boş bırakılırsa silinir.
    if "youtube_api_keys" in request.form:
        raw = request.form.get("youtube_api_keys", "")
        keys, seen = [], set()
        for line in raw.splitlines():
            k = line.strip()
            if k and k not in seen:
                seen.add(k); keys.append(k)
        if keys:
            secrets["youtube_api_keys"] = keys
        else:
            secrets.pop("youtube_api_keys", None)
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

    # ai33 API key — separate file (seslendirmeli/voiced kanallar için TTS)
    new_ai33_key = request.form.get("ai33_api_key", "").strip()
    clear_ai33 = request.form.get("ai33_api_key_clear") == "1"
    if new_ai33_key:
        secrets["ai33_api_key"] = new_ai33_key
        _save_secrets(secrets)
    elif clear_ai33:
        secrets.pop("ai33_api_key", None)
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


@bp.route("/settings/storyblocks/connect", methods=["POST"])
def storyblocks_connect():
    """Masaüstünde headed tarayıcı aç (arka planda) — kullanıcı Storyblocks'a girsin."""
    _launch_storyblocks_login(_storyblocks_session_path())
    flash("Storyblocks giriş penceresi açıldı — tarayıcıda giriş yap, oturum kaydedilecek.",
          "success")
    return redirect(url_for("settings.view"))


@bp.route("/settings/storyblocks/disconnect", methods=["POST"])
def storyblocks_disconnect():
    """Kayıtlı Storyblocks oturum dosyasını sil."""
    _delete_storyblocks_session(_storyblocks_session_path())
    flash("Storyblocks oturumu silindi.", "success")
    return redirect(url_for("settings.view"))


@bp.route("/settings/assets/build", methods=["POST"])
def assets_build():
    """Ses kütüphanesini Mixkit'ten kur/genişlet (arka planda; anahtar gerekmez).

    Var olan dosya yeniden indirilmez → düğmeye tekrar basmak kütüphaneyi BÜYÜTÜR.
    Kütüphane ne kadar genişse AI kurgucunun eli o kadar rahat (aynı ses tekrarlanmaz).
    """
    if _LIB_BUILD.get("running"):
        flash("Kütüphane kurulumu zaten sürüyor.", "error")
        return redirect(url_for("settings.view"))
    per_sfx = max(1, min(40, int(request.form.get("per_sfx") or 15)))
    per_music = max(1, min(40, int(request.form.get("per_music") or 10)))
    _launch_library_build(_assets_root(), per_sfx, per_music)
    flash(f"Kütüphane kurulumu başladı (kategori başına {per_sfx} SFX, "
          f"{per_music} müzik). Sayfayı birkaç dakika sonra yenile.", "success")
    return redirect(url_for("settings.view"))
