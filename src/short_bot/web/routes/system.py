"""System actions: restart the server from the UI."""
from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Blueprint, flash, redirect, request, url_for

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
