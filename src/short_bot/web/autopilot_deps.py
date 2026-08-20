"""Autopilot'un GERÇEK yan etkileri.

Runner bunları AutopilotDeps olarak enjekte alır; testler sahte verir. Ağ, LLM,
kimlik doğrulama ve pipeline YALNIZ burada — böylece durum makinesi (autopilot_runner)
tamamen izole test edilebiliyor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from short_bot.autopilot_runner import AutopilotDeps
from short_bot.config import resolve_ai_call
from short_bot.pipeline import run_pipeline
from short_bot.youtube import auth as _yt_auth
from short_bot.youtube.auto_upload import run_auto_upload


def _secrets(app) -> dict:
    try:
        sp = app.config["SHORTBOT_SECRETS_PATH"]
        return (yaml.safe_load(sp.read_text(encoding="utf-8"))
                if sp.exists() else {}) or {}
    except Exception:
        return {}


def _llm(app):
    try:
        return resolve_ai_call(app.config["SHORTBOT_SETTINGS"], _secrets(app),
                               "default")
    except Exception:
        return None


def _creds(app, cfg):
    root = (Path(app.config["SHORTBOT_DB_PATH"]).parent
            / "youtube_credentials").resolve()
    return _yt_auth.load_credentials(root, _yt_auth.creds_slug(cfg))


def build_deps(app, cfg) -> AutopilotDeps:
    def _produce(channel, series: bool = True):
        # defer_upload=True ŞART: yüklemeyi AUTOPILOT yapacak (slot saatine, gizli +
        # publishAt). Pipeline da yüklerse kanalda İKİ video olur — biri anında public,
        # biri zamanlı — ve bütün zamanlama çöker. Hiçbir hata vermez.
        #
        # standalone=not series: bağımsız slot seriyi İLERLETMEZ (ark tüketilmez).
        # Günde en fazla 1 bölüm — yoksa "#2 yarın" sözü aynı gün bozulur.
        return run_pipeline(
            channel=channel, settings=app.config["SHORTBOT_SETTINGS"],
            db_path=app.config["SHORTBOT_DB_PATH"],
            music_root=app.config["SHORTBOT_MUSIC_ROOT"],
            templates_dir=app.config["SHORTBOT_TEMPLATES_DIR"],
            cache_dir=app.config["SHORTBOT_CACHE_DIR"],
            lock_dir=app.config["SHORTBOT_LOCK_DIR"],
            logs_dir=app.config["SHORTBOT_LOGS_DIR"],
            trigger="autopilot", defer_upload=True, standalone=not series)

    def _upload(short_id, channel, publish_at=None):
        from short_bot.db import init_db
        eng = init_db(app.config["SHORTBOT_DB_PATH"])
        creds = _creds(app, channel)
        if creds is None:
            raise RuntimeError("YouTube kanalı bağlanmamış (token.json yok)")
        call = _llm(app)
        r = run_auto_upload(
            eng=eng, short_id=short_id, channel=channel, credentials=creds,
            claude_path=(call.claude_path if call else "claude"),
            model=(call.model if call else "sonnet"),
            backend=(call.backend if call else "claude_cli"),
            api_key=(call.api_key if call else None),
            secrets_path=app.config["SHORTBOT_SECRETS_PATH"],
            publish_at=publish_at)
        return r.video_url

    def _ensure_arc(channel):
        from short_bot.autopilot_arc import ensure_arc
        from short_bot.db import init_db
        ensure_arc(init_db(app.config["SHORTBOT_DB_PATH"]), channel,
                   llm_call=_llm(app))

    return AutopilotDeps(
        produce=_produce,
        upload_scheduled=lambda sid, ch, pa: _upload(sid, ch, publish_at=pa),
        upload_live=lambda sid, ch: _upload(sid, ch, publish_at=None),
        ensure_arc=_ensure_arc,
        now=lambda: datetime.now(timezone.utc))
