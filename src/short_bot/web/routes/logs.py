from pathlib import Path

from flask import Blueprint, current_app, render_template

bp = Blueprint("logs", __name__)


def _read_recent_lines(logs_dir: Path, max_lines: int = 200) -> list[str]:
    files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[str] = []
    for fp in files[:5]:  # last 5 log files
        try:
            content = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            out.extend([f"[{fp.stem}] {line}" for line in content[-50:]])
            if len(out) >= max_lines:
                break
        except OSError:
            continue
    return out[-max_lines:]


@bp.route("/logs")
def list_view():
    return render_template("logs.html.j2")


@bp.route("/logs/tail")
def tail_partial():
    logs_dir = current_app.config["SHORTBOT_LOGS_DIR"]
    lines = _read_recent_lines(logs_dir)
    return render_template("_partials/log_tail.html.j2", lines=lines)
