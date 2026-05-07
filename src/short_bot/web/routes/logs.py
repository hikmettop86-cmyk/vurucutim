import re
from pathlib import Path

from flask import (Blueprint, abort, current_app, render_template, request,
                   send_file)

bp = Blueprint("logs", __name__)


_LEVEL_PATTERNS = {
    "ERROR": re.compile(r"\bERROR\b", re.IGNORECASE),
    "WARNING": re.compile(r"\bWARN(?:ING)?\b", re.IGNORECASE),
    "INFO": re.compile(r"\bINFO\b", re.IGNORECASE),
    "DEBUG": re.compile(r"\bDEBUG\b", re.IGNORECASE),
}


def _channel_from_filename(stem: str) -> str:
    """Filename pattern: 20260101_120000_<channel-slug>.log → returns channel slug."""
    parts = stem.split("_", 2)
    return parts[2] if len(parts) >= 3 else ""


def _read_recent_lines(
    logs_dir: Path, max_lines: int = 200,
    channel: str = "", level: str = "", q: str = "",
) -> list[str]:
    files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if channel:
        files = [f for f in files if _channel_from_filename(f.stem) == channel]
    out: list[str] = []
    level_re = _LEVEL_PATTERNS.get(level.upper())
    q_lower = q.lower() if q else ""
    for fp in files[:10]:  # last 10 files
        try:
            content = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in content[-200:]:
                if level_re and not level_re.search(line):
                    continue
                if q_lower and q_lower not in line.lower():
                    continue
                out.append(f"[{fp.stem}] {line}")
            if len(out) >= max_lines:
                break
        except OSError:
            continue
    return out[-max_lines:]


def _list_log_channels(logs_dir: Path) -> list[str]:
    seen: set[str] = set()
    for fp in logs_dir.glob("*.log"):
        ch = _channel_from_filename(fp.stem)
        if ch:
            seen.add(ch)
    return sorted(seen)


@bp.route("/logs")
def list_view():
    logs_dir = current_app.config["SHORTBOT_LOGS_DIR"]
    return render_template(
        "logs.html.j2",
        channel=request.args.get("channel", ""),
        level=request.args.get("level", ""),
        q=request.args.get("q", ""),
        log_channels=_list_log_channels(logs_dir),
    )


@bp.route("/logs/tail")
def tail_partial():
    logs_dir = current_app.config["SHORTBOT_LOGS_DIR"]
    lines = _read_recent_lines(
        logs_dir,
        channel=request.args.get("channel", ""),
        level=request.args.get("level", ""),
        q=request.args.get("q", ""),
    )
    return render_template("_partials/log_tail.html.j2", lines=lines)


@bp.route("/logs/clear", methods=["POST"])
def clear():
    """Delete all *.log files in the logs directory. Skips files held open by the OS."""
    logs_dir: Path = current_app.config["SHORTBOT_LOGS_DIR"]
    for fp in logs_dir.glob("*.log"):
        try:
            fp.unlink()
        except OSError:
            continue
    return ("", 204)


@bp.route("/logs/download")
def download():
    """Download the most recent log file (or by ?file=<stem>)."""
    logs_dir: Path = current_app.config["SHORTBOT_LOGS_DIR"]
    file_stem = request.args.get("file", "").strip()
    if file_stem:
        # Prevent path traversal
        if "/" in file_stem or "\\" in file_stem or ".." in file_stem:
            abort(400)
        target = logs_dir / f"{file_stem}.log"
        if not target.exists():
            abort(404)
    else:
        files = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            abort(404)
        target = files[0]
    return send_file(target, as_attachment=True, download_name=target.name)
