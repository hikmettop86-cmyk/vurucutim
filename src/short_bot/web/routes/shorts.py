from datetime import datetime

from flask import (Blueprint, abort, current_app, flash, make_response,
                   redirect, render_template, request, url_for)

from short_bot.config import load_channel
from short_bot.web.extensions import db
from short_bot.web.models import Short
from short_bot.web.runs import launch_pipeline

bp = Blueprint("shorts", __name__)


@bp.route("/shorts")
def list_view():
    from short_bot.config import list_channels
    channel = request.args.get("channel", "").strip()
    q = request.args.get("q", "").strip()
    query = Short.query.filter(Short.deleted_at.is_(None))
    if channel:
        query = query.filter(Short.channel == channel)
    if q:
        query = query.filter(Short.title.ilike(f"%{q}%"))
    shorts = query.order_by(Short.created_at.desc()).limit(60).all()
    all_channels = list_channels(
        current_app.config["SHORTBOT_CONFIG_DIR"] / "channels", enabled_only=False
    )
    return render_template("shorts/list.html.j2",
                            channel=channel,
                            q=q,
                            shorts=shorts,
                            all_channels=all_channels)


@bp.route("/shorts/grid")
def grid_partial():
    """HTMX partial: filter result grid swap."""
    channel = request.args.get("channel", "").strip()
    q = request.args.get("q", "").strip()
    query = Short.query.filter(Short.deleted_at.is_(None))
    if channel:
        query = query.filter(Short.channel == channel)
    if q:
        query = query.filter(Short.title.ilike(f"%{q}%"))
    shorts = query.order_by(Short.created_at.desc()).limit(60).all()
    return render_template("_partials/shorts_grid.html.j2", shorts=shorts)


@bp.route("/shorts/<int:short_id>")
def detail(short_id):
    s = Short.query.filter_by(id=short_id).first()
    if s is None or s.deleted_at is not None:
        abort(404)
    from short_bot.youtube import auth as _yt_auth
    from short_bot.web.models import YoutubeUpload
    yt_root = current_app.config.get("SHORTBOT_YT_CREDS_DIR")
    yt_connected = bool(yt_root and _yt_auth.has_credentials(yt_root, s.channel))
    yt_upload = (YoutubeUpload.query.filter_by(short_id=s.id)
                 .order_by(YoutubeUpload.uploaded_at.desc()).first())
    return render_template("shorts/detail.html.j2", s=s,
                           yt_connected=yt_connected, yt_upload=yt_upload)


@bp.route("/shorts/run-now", methods=["POST"])
def run_now():
    """HTMX action: launch pipeline for the given channel slug and return status partial."""
    slug = request.form.get("slug", "").strip()
    if not slug:
        abort(400)
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channel_path = cfg_dir / "channels" / f"{slug}.yaml"
    if not channel_path.exists():
        abort(404)
    channel = load_channel(channel_path)
    launch_pipeline(
        channel=channel,
        settings=current_app.config["SHORTBOT_SETTINGS"],
        db_path=current_app.config["SHORTBOT_DB_PATH"],
        music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
        templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
        cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
        lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
        logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
        trigger="manual",
    )
    flash(f"'{slug}' için pipeline başlatıldı (arka planda).", "success")
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Refresh"] = "true"
        return resp
    return render_template("_partials/run_status.html.j2", status="running", run_id=None)


@bp.route("/shorts/<int:short_id>/delete", methods=["POST"])
def delete(short_id):
    """Soft-delete a short by setting deleted_at timestamp."""
    s = Short.query.filter_by(id=short_id).first()
    if s is None or s.deleted_at is not None:
        abort(404)
    s.deleted_at = datetime.utcnow()
    db.session.commit()
    flash(f"'{s.title}' silindi.", "success")
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Redirect"] = url_for("shorts.list_view")
        return resp
    return redirect(url_for("shorts.list_view"))
