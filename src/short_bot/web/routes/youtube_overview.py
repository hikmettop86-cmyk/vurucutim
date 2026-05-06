from pathlib import Path
from flask import Blueprint, current_app, render_template

from short_bot.config import list_channels
from short_bot.db import init_db, get_channel_stats_history
from short_bot.youtube import auth as _yt_auth

bp = Blueprint("youtube_overview", __name__)


@bp.route("/youtube")
def index():
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    yt_root = Path(current_app.config["SHORTBOT_YT_CREDS_DIR"])

    channels = list_channels(cfg_dir / "channels", enabled_only=False)
    summaries = []
    for ch in channels:
        if not _yt_auth.has_credentials(yt_root, ch.slug):
            continue
        info = _yt_auth.load_channel_info(yt_root, ch.slug) or {}
        history = get_channel_stats_history(eng, channel=ch.slug, days=30)
        latest = history[0] if history else None
        summaries.append({
            "slug": ch.slug,
            "name": ch.name,
            "yt_title": info.get("snippet", {}).get("title", ch.slug),
            "subscribers": latest.subscribers if latest else None,
            "total_views": latest.total_views if latest else None,
            "history_days": len(history),
            "latest_snapshot": (latest.snapshot_date if latest else None),
        })
    return render_template("youtube/index.html.j2", summaries=summaries)
