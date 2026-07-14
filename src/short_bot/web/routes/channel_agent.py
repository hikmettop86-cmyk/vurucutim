"""Kanal kurma ajanı paneli: bir cümle → çalışan bir kanal.

İKİ AŞAMA (kasıtlı): plan HAZIRLANIR ve GÖSTERİLİR, kullanıcı "Kur"a basar. Ajan
yanlış ses seçtiyse ya da niş kaydıysa, kanal KURULMADAN görülür.

Plan hazırlamak ~2-3 dk sürüyor (dil paketi + ses + DNA + örnek konular) → daemon
thread + HTMX poll. Desen niche_finder'ın iş kuyruğundan alındı (reel_new.py).
"""
from __future__ import annotations

import logging
import threading
import uuid

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.channel_agent import apply_plan, build_plan
from short_bot.locale import LANGUAGE_NAMES, SUPPORTED_LANGUAGES
from short_bot.web.niche_finder import find_niches_ai, find_niches_data

bp = Blueprint("channel_agent", __name__)
_LOG = logging.getLogger(__name__)

# Bellek-içi iş kuyruğu (niche_finder deseni). Panel tek kullanıcılı bir masaüstü
# uygulaması; kalıcı kuyruk gerekmiyor.
_JOBS: dict = {}
_PLANS: dict = {}
_NICHES: dict = {}
_LOCK = threading.Lock()


def _start_thread(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _set_job(job_id: str, **fields) -> None:
    with _LOCK:
        _JOBS.setdefault(job_id, {}).update(fields)


def _get_job(job_id: str):
    with _LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else None


def _secrets() -> dict:
    import yaml
    try:
        sp = current_app.config["SHORTBOT_SECRETS_PATH"]
        return (yaml.safe_load(sp.read_text(encoding="utf-8"))
                if sp.exists() else {}) or {}
    except Exception:   # noqa: BLE001
        return {}


def _sonnet():
    from short_bot.llm_sonnet import sonnet_json
    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets = _secrets()

    def _f(prompt, schema, **kw):
        return sonnet_json(prompt, schema,
                           claude_path=settings.claude_cli_path,
                           openrouter_model=settings.openrouter_models.get(
                               "script", "anthropic/claude-sonnet-5"),
                           openrouter_key=secrets.get("openrouter_api_key"))
    return _f


def _diller():
    return [(k, LANGUAGE_NAMES[k]) for k in SUPPORTED_LANGUAGES]


@bp.get("/channels/agent")
def page():
    return render_template("channel_agent.html.j2", languages=_diller(),
                           plan=None, niches=None, job=None, job_id=None)


@bp.get("/channels/agent/status/<job_id>")
def status(job_id):
    job = _get_job(job_id)
    if job is None:
        abort(404)
    with _LOCK:
        p = _PLANS.get(job_id)
        n = _NICHES.get(job_id)
    return render_template("channel_agent.html.j2", languages=_diller(),
                           plan=p, niches=n, job=job, job_id=job_id)


# --- NİŞ BUL ---------------------------------------------------------------

@bp.post("/channels/agent/find")
def find():
    """Niş bul: LLM adaylar üretir, YouTube outlier verisi HAKEMLİK eder.

    YouTube anahtarı yoksa AI moduna düşülür — adaylar gelir ama KANIT YOKTUR ve panel
    bunu söyler. Uydurma kanıt yazmayız.
    """
    query = (request.form.get("query") or "").strip()
    language = (request.form.get("language") or "tr").strip()
    if language not in SUPPORTED_LANGUAGES:
        language = "tr"
    if len(query) < 3:
        flash("Ne hakkında kanal istediğini yaz (ör. 'Almanya', 'bahçecilik').",
              "error")
        return redirect(url_for("channel_agent.page"))

    from short_bot.yt_outliers import resolve_youtube_api_keys
    secrets = _secrets()
    settings = current_app.config["SHORTBOT_SETTINGS"]
    api_keys = resolve_youtube_api_keys(secrets)
    or_model = settings.openrouter_models.get("dna", "anthropic/claude-opus-4.8")
    or_key = secrets.get("openrouter_api_key")

    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="running", error="", kind="find", language=language)

    def _job():
        try:
            if api_keys:
                out = find_niches_data(
                    query, language=language, count=6, api_keys=api_keys,
                    claude_path=settings.claude_cli_path,
                    openrouter_model=or_model, openrouter_key=or_key)
            else:
                # KANIT YOK — panel bunu söyleyecek.
                out = find_niches_ai(
                    query, language=language, count=6,
                    claude_path=settings.claude_cli_path,
                    openrouter_model=or_model, openrouter_key=or_key)
            with _LOCK:
                _NICHES[job_id] = out
            _set_job(job_id, status="done", kanitli=bool(api_keys))
        except Exception as e:   # noqa: BLE001 — kullanıcıya SEBEBİ söyle
            _LOG.warning(f"[ajan] niş bulucu: {e}")
            _set_job(job_id, status="error", error=str(e))

    _start_thread(_job)
    return redirect(url_for("channel_agent.status", job_id=job_id))


# --- PLAN ------------------------------------------------------------------

@bp.post("/channels/agent/plan")
def plan():
    niche = (request.form.get("niche") or "").strip()
    language = (request.form.get("language") or "tr").strip()
    if language not in SUPPORTED_LANGUAGES:
        language = "tr"
    if len(niche) < 10:
        flash("Niş en az 10 karakter olmalı — ne hakkında kanal istediğini yaz.",
              "error")
        return redirect(url_for("channel_agent.page"))

    from short_bot.tts.ai33_client import resolve_ai33_api_key
    secrets = _secrets()
    settings = current_app.config["SHORTBOT_SETTINGS"]
    channels_dir = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels"
    ai33_key = resolve_ai33_api_key(secrets)
    evidence = (request.form.get("evidence") or "").strip()
    llm = _sonnet()

    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="running", error="", kind="plan", language=language)

    def _job():
        try:
            p = build_plan(niche, language=language, channels_dir=channels_dir,
                           ai33_key=ai33_key, settings=settings, secrets=secrets,
                           llm=llm, evidence=evidence)
            with _LOCK:
                _PLANS[job_id] = p
            _set_job(job_id, status="done")
        except Exception as e:   # noqa: BLE001 — kullanıcıya SEBEBİ söyle
            _LOG.warning(f"[ajan] plan kurulamadı: {e}")
            _set_job(job_id, status="error", error=str(e))

    _start_thread(_job)
    return redirect(url_for("channel_agent.status", job_id=job_id))


@bp.post("/channels/agent/apply/<job_id>")
def apply(job_id):
    with _LOCK:
        p = _PLANS.get(job_id)
    if p is None:
        abort(404)
    try:
        slug = apply_plan(
            p,
            channels_dir=current_app.config["SHORTBOT_CONFIG_DIR"] / "channels",
            templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
            db_path=current_app.config["SHORTBOT_DB_PATH"],
            settings=current_app.config["SHORTBOT_SETTINGS"],
            secrets=_secrets(), llm=_sonnet())
    except Exception as e:   # noqa: BLE001
        flash(f"Kanal kurulamadı: {e}", "error")
        return redirect(url_for("channel_agent.status", job_id=job_id))

    with _LOCK:
        _PLANS.pop(job_id, None)
        _JOBS.pop(job_id, None)
    flash(f"'{p.name}' kuruldu. Konu bankası tohumlandı. Otomasyon KAPALI — açmak "
          f"istersen Otomasyon sayfasından.", "success")
    return redirect(f"/channels/{slug}")
