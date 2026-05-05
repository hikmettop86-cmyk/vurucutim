from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, current_app, render_template
from sqlalchemy import func

from short_bot.config import list_channels
from short_bot.web.extensions import db
from short_bot.web.models import Run, Short

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())

    total_shorts = Short.query.filter(Short.deleted_at.is_(None)).count()
    today_shorts = Short.query.filter(
        Short.deleted_at.is_(None),
        Short.created_at >= today_start,
    ).count()
    failed_runs_24h = Run.query.filter(
        Run.status == "failed",
        Run.started_at >= datetime.utcnow() - timedelta(hours=24),
    ).count()

    channels = list_channels(current_app.config["SHORTBOT_CONFIG_DIR"] / "channels",
                              enabled_only=False)
    recent = (Short.query
              .filter(Short.deleted_at.is_(None))
              .order_by(Short.created_at.desc())
              .limit(4).all())

    return render_template(
        "dashboard.html.j2",
        total_shorts=total_shorts,
        today_shorts=today_shorts,
        failed_runs=failed_runs_24h,
        channel_count=len(channels),
        channels=channels,
        recent=recent,
    )
