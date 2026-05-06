from pathlib import Path
from flask import Blueprint, current_app, render_template

from short_bot.config import list_channels
from short_bot.db import init_db, get_channel_stats_history
from short_bot.youtube import auth as _yt_auth

bp = Blueprint("youtube_overview", __name__)


@bp.route("/youtube")
def index():
    from datetime import date, timedelta
    from short_bot.db import (
        count_uploads_for_channel, last_upload_at_for_channel,
    )
    from short_bot.youtube.avatar import has_avatar

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
        # 7-day delta
        target_iso = (date.today() - timedelta(days=7)).isoformat()
        week_ago = next((h for h in history if h.snapshot_date <= target_iso), None)
        subs_delta = (latest.subscribers - week_ago.subscribers) if (latest and week_ago) else None
        views_delta = (latest.total_views - week_ago.total_views) if (latest and week_ago) else None
        snippet = info.get("snippet", {}) or {}
        stats_block = info.get("statistics", {}) or {}
        bot_uploads = count_uploads_for_channel(eng, ch.slug)
        last_up = last_upload_at_for_channel(eng, ch.slug)
        summaries.append({
            "slug": ch.slug,
            "name": ch.name,
            "yt_title": snippet.get("title", ch.slug),
            "yt_handle": (snippet.get("customUrl") or "").lstrip("@") or ch.handle.lstrip("@"),
            "yt_description_short": (snippet.get("description") or "")[:180],
            "subscribers": latest.subscribers if latest else None,
            "total_views": latest.total_views if latest else None,
            "video_count": int(stats_block.get("videoCount", 0)) if stats_block else 0,
            "subs_delta_7d": subs_delta,
            "views_delta_7d": views_delta,
            "bot_uploaded": bot_uploads,
            "last_upload_at": last_up,
            "snapshot": latest.snapshot_date if latest else None,
            "history_days": len(history),
            "has_avatar": has_avatar(yt_root, ch.slug),
        })
    return render_template("youtube/index.html.j2", summaries=summaries)
