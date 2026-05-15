"""System actions: restart the server from the UI."""
from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, request, url_for

bp = Blueprint("system", __name__)


@bp.route("/healthz")
def healthz():
    """Liveness/readiness probe — used by Electron to detect Flask boot.

    Returns 200 + JSON payload as soon as the Flask app is serving requests.
    DB connections + scheduler are checked indirectly: if create_app() failed
    they wouldn't have reached here.
    """
    try:
        version = importlib.metadata.version("short-bot")
    except importlib.metadata.PackageNotFoundError:
        version = "0.0.0-dev"
    return {"status": "ok", "version": version}


@bp.route("/system/scheduler")
def scheduler_status():
    """Diagnostic endpoint — durum kontrolu icin tarayicidan acilir.

    Cron'larin gercekten registered ve next_run_time'lari ne olduklari gorulur.
    'Cron'lar calismiyor' sikayetinin ilk hedefi. JSON dondurur.
    """
    from flask import current_app, jsonify
    sched = getattr(current_app, "scheduler", None)
    if sched is None:
        return jsonify({
            "running": False,
            "error": "Scheduler hic baslatilmamis (init_scheduler cagrilmadi)",
            "jobs": [],
        }), 200
    try:
        running = bool(sched.running)
    except Exception:
        running = False
    jobs_info = []
    try:
        for j in sched.get_jobs():
            jobs_info.append({
                "id": j.id,
                "next_run_time": str(j.next_run_time) if j.next_run_time else None,
                "trigger": str(j.trigger),
                "max_instances": j.max_instances,
            })
    except Exception as e:
        jobs_info = [{"error": str(e)}]
    # Recent runs (last 10) for diagnosing 'cron'lar calismiyor' issues
    recent_runs = []
    try:
        from short_bot.web.models import Run
        rows = Run.query.order_by(Run.started_at.desc()).limit(10).all()
        for r in rows:
            recent_runs.append({
                "id": r.id,
                "channel": r.channel,
                "started_at": str(r.started_at) if r.started_at else None,
                "status": r.status,
                "trigger": getattr(r, "trigger", None),
                "error": (r.error[:200] if r.error else None),
            })
    except Exception as e:
        recent_runs = [{"error": str(e)}]

    return jsonify({
        "running": running,
        "job_count": len(jobs_info),
        "jobs": jobs_info,
        "recent_runs": recent_runs,
    })


@bp.route("/scheduler/timeline")
def scheduler_timeline():
    """Bugün ve yarın için hangi kanalın ne zaman tetikleneceğini görselleştirir."""
    from datetime import datetime, timedelta, timezone
    from flask import current_app, render_template

    sched = getattr(current_app, "scheduler", None)
    fires = []  # list of dicts: {slug, time}

    if sched is not None and sched.running:
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=48)
        for j in sched.get_jobs():
            if j.id == "_reload_jobs":
                continue
            try:
                trigger = j.trigger
                t = j.next_run_time
                count = 0
                while t and t < end and count < 100:
                    fires.append({"slug": j.id, "time": t.astimezone()})
                    t = trigger.get_next_fire_time(t, t + timedelta(seconds=1))
                    count += 1
            except Exception:
                continue

    fires.sort(key=lambda x: x["time"])
    return render_template("scheduler_timeline.html.j2",
                           fires=fires,
                           generated_at=datetime.now().astimezone())


def _project_root() -> Path:
    # web/routes/system.py → web/routes → web → short_bot → src → repo root
    return Path(__file__).resolve().parents[4]


def _spawn_replacement():
    """Launch a fresh, detached server. Order matters:
    - on Windows we prefer the VBS launcher (its 2.5s sleep gives our process
      time to die and release port 5005)
    - otherwise launch python directly with a small startup delay
    """
    root = _project_root()
    vbs = root / "start_silent.vbs"

    if sys.platform == "win32" and vbs.exists():
        DETACHED = 0x00000008  # subprocess.DETACHED_PROCESS
        NEW_GROUP = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            ["wscript", str(vbs)],
            cwd=str(root),
            creationflags=DETACHED | NEW_GROUP,
            close_fds=True,
        )
        return

    # Generic fallback: helper Python that waits then runs the server
    helper = (
        "import time, subprocess, sys, os; "
        f"os.chdir(r'{root}'); "
        "time.sleep(2.5); "
        f"subprocess.Popen([sys.executable, '-m', 'short_bot', 'web'], "
        f"cwd=r'{root}')"
    )
    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000008 | 0x00000200
    subprocess.Popen(
        [sys.executable, "-c", helper],
        cwd=str(root),
        creationflags=creationflags,
        close_fds=True,
    )


@bp.route("/system/backfill-embeddings", methods=["POST"])
def backfill_embeddings():
    """Retroactively populate produced-headline embeddings for shorts that
    pre-date the dedup-v2 feature. Idempotent — re-running is safe."""
    from short_bot.db import init_db, backfill_produced_embeddings
    from short_bot.pexels import load_secrets as _load_secrets, resolve_openai_api_key
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    if not secrets_path:
        flash("Secrets path yok — backfill atlandı.", "error")
        return redirect(url_for("dashboard.index"))
    api_key = resolve_openai_api_key(_load_secrets(Path(secrets_path)))
    if not api_key:
        flash("OpenAI API key tanımlı değil. /settings'ten ekle.", "error")
        return redirect(url_for("settings.view"))
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    result = backfill_produced_embeddings(eng, api_key, days=14)
    msg = (f"Backfill tamam: {result['updated']} güncellendi, "
           f"{result['skipped']} atlandı, {result['errors']} hata.")
    flash(msg, "success" if result["updated"] > 0 or result["errors"] == 0
                       else "warning")
    return redirect(url_for("dashboard.index"))


@bp.route("/system/restart", methods=["POST"])
def restart():
    _spawn_replacement()

    # Give Flask a moment to flush the response, then kill the current process
    # so port 5005 is released before the new instance binds.
    def _quit():
        time.sleep(1.2)
        os._exit(0)
    threading.Thread(target=_quit, daemon=True).start()

    flash("Sunucu yeniden başlatılıyor — birkaç saniye sonra sayfa yenilenecek.",
          "success")
    if request.headers.get("HX-Request"):
        from flask import make_response
        resp = make_response("", 200)
        # Tell HTMX the client to refresh after ~5 seconds via JS
        resp.headers["HX-Trigger"] = "schedule-refresh"
        return resp
    return redirect(url_for("dashboard.index"))
