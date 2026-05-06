from datetime import datetime, timedelta
from pathlib import Path as _Path

from flask import Blueprint, current_app, render_template
from sqlalchemy import func

from short_bot.config import list_channels
from short_bot.db import init_db, get_channel_stats_history
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

    from short_bot.youtube import auth as _yt_auth
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    yt_root = _Path(current_app.config["SHORTBOT_YT_CREDS_DIR"])
    channels_for_yt = list_channels(
        current_app.config["SHORTBOT_CONFIG_DIR"] / "channels", enabled_only=False,
    )
    yt_summaries = []
    for ch in channels_for_yt:
        if not _yt_auth.has_credentials(yt_root, ch.slug):
            continue
        info = _yt_auth.load_channel_info(yt_root, ch.slug) or {}
        history = get_channel_stats_history(eng, channel=ch.slug, days=7)
        latest = history[0] if history else None
        yt_summaries.append({
            "slug": ch.slug,
            "name": ch.name,
            "yt_title": info.get("snippet", {}).get("title", ch.slug),
            "subscribers": latest.subscribers if latest else None,
            "total_views": latest.total_views if latest else None,
            "history_days": len(history),
        })

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
        yt_summaries=yt_summaries,
    )
