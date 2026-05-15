from datetime import datetime, timedelta, timezone

from flask import (Blueprint, current_app, flash, make_response,
                   redirect, render_template, request, url_for)

from short_bot.config import list_channels
from short_bot.db import clear_recent_failed_runs, init_db
from short_bot.dna_cache import get_cache_stats
from short_bot.web.extensions import db
from short_bot.web.models import Run, Short, YoutubeUpload

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    now = datetime.utcnow()
    today_start = datetime.combine(now.date(), datetime.min.time())

    total_shorts = Short.query.filter(Short.deleted_at.is_(None)).count()
    today_shorts = Short.query.filter(
        Short.deleted_at.is_(None),
        Short.created_at >= today_start,
    ).count()
    last_hour_shorts = Short.query.filter(
        Short.deleted_at.is_(None),
        Short.created_at >= now - timedelta(hours=1),
    ).count()
    youtube_uploaded = (db.session.query(YoutubeUpload.short_id)
                        .filter(YoutubeUpload.status == "success")
                        .distinct().count())
    yesterday = now - timedelta(hours=24)
    auto_uploads_24h = YoutubeUpload.query.filter(
        YoutubeUpload.status == "success",
        YoutubeUpload.uploaded_at >= yesterday,
    ).count()
    failed_runs_24h = Run.query.filter(
        Run.status == "failed",
        Run.started_at >= now - timedelta(hours=24),
    ).count()

    channels = list_channels(current_app.config["SHORTBOT_CONFIG_DIR"] / "channels",
                              enabled_only=False)
    recent = (Short.query
              .filter(Short.deleted_at.is_(None))
              .order_by(Short.created_at.desc())
              .limit(4).all())

    # Last 5 failed runs in last 24h for error panel
    since_utc = datetime.now(timezone.utc) - timedelta(hours=24)
    # Support both tz-aware and tz-naive started_at columns
    since_naive = datetime.utcnow() - timedelta(hours=24)
    recent_errors = (Run.query
                     .filter(Run.status == "failed",
                             Run.started_at >= since_naive)
                     .order_by(Run.started_at.desc())
                     .limit(5).all())

    # Build per-channel cache stats for dynamic_dna channels only
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    cache_stats = {}
    for ch in channels:
        if ch.dynamic_dna:
            cache_stats[ch.slug] = get_cache_stats(eng, ch.slug)

    return render_template(
        "dashboard.html.j2",
        total_shorts=total_shorts,
        today_shorts=today_shorts,
        last_hour_shorts=last_hour_shorts,
        youtube_uploaded=youtube_uploaded,
        auto_uploads_24h=auto_uploads_24h,
        failed_runs=failed_runs_24h,
        channel_count=len(channels),
        channels=channels,
        recent=recent,
        recent_errors=recent_errors,
        cache_stats=cache_stats,
    )


@bp.route("/dashboard/clear-errors", methods=["POST"])
def clear_errors():
    """Backs the 'Hataları temizle' button on the recent-errors panel.
    Deletes the failed run DB rows from the last 24h; run log files on disk
    are NOT touched (still browsable via /logs if user needs history)."""
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    deleted = clear_recent_failed_runs(eng, hours=24)
    if deleted:
        flash(f"{deleted} hata kaydı silindi.", "success")
    else:
        flash("Silinecek hata yok.", "info")
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Redirect"] = url_for("dashboard.index")
        return resp
    return redirect(url_for("dashboard.index"))
