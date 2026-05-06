from pathlib import Path
from flask import (Blueprint, abort, current_app, flash, redirect,
                   request, url_for)

from short_bot.youtube import auth as yt_auth

bp = Blueprint("youtube", __name__)


def _yt_root() -> Path:
    return Path(current_app.config["SHORTBOT_YT_CREDS_DIR"])


def _redirect_uri() -> str:
    s = current_app.config["SHORTBOT_SETTINGS"]
    host = getattr(s, "web_host", "127.0.0.1")
    port = getattr(s, "web_port", 5005)
    return f"http://{host}:{port}/oauth/callback"


@bp.route("/channels/<slug>/youtube/connect", methods=["POST"])
def connect(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    try:
        flow = yt_auth.build_flow(_yt_root(), slug, redirect_uri=_redirect_uri())
    except FileNotFoundError:
        flash(f"client_secrets.json eksik. Yere bırak: data/youtube_credentials/{slug}/client_secrets.json",
              "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    auth_url, _state = flow.authorization_url(
        state=slug, access_type="offline", prompt="consent",
    )
    return redirect(auth_url)


@bp.route("/oauth/callback")
def callback():
    state = request.args.get("state", "")
    code = request.args.get("code", "")
    if not state or not code:
        abort(400)
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{state}.yaml"
    if not cfg_path.exists():
        abort(404)
    try:
        flow = yt_auth.build_flow(_yt_root(), state, redirect_uri=_redirect_uri())
        flow.fetch_token(code=code)
        creds = flow.credentials
        yt_auth.save_credentials(_yt_root(), state, creds)
        info = yt_auth.fetch_and_save_channel_info(_yt_root(), state, creds)
        title = info.get("snippet", {}).get("title", state)
        flash(f"YouTube kanalı bağlandı: {title}", "success")
    except Exception as e:
        flash(f"YouTube bağlantı başarısız: {e}", "error")
    return redirect(url_for("channel_edit.edit", slug=state))


@bp.route("/channels/<slug>/youtube/disconnect", methods=["POST"])
def disconnect(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    yt_auth.delete_credentials(_yt_root(), slug)
    flash("YouTube bağlantısı kaldırıldı.", "success")
    return redirect(url_for("channel_edit.edit", slug=slug))
