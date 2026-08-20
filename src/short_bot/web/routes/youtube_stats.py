from pathlib import Path
from flask import (Blueprint, abort, current_app, flash, redirect, url_for)

from short_bot.db import init_db
from short_bot.youtube.stats_refresh import refresh_channel_stats

bp = Blueprint("youtube_stats", __name__)


@bp.route("/channels/<slug>/youtube/refresh-stats", methods=["POST"])
def refresh(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    yt_root = Path(current_app.config["SHORTBOT_YT_CREDS_DIR"])
    try:
        from short_bot.config import load_channel
        from short_bot.youtube import auth as _yt_auth
        result = refresh_channel_stats(
            eng=eng, channel_slug=slug, yt_creds_root=yt_root,
            video_lookback_days=30,
            creds_slug=_yt_auth.creds_slug(load_channel(cfg_path)),
        )
        if result.skipped_reason:
            flash(f"Stats çekilemedi: {result.skipped_reason}", "error")
        else:
            flash(f"Stats güncellendi — {result.video_count} video, "
                   f"kanal {'güncellendi' if result.channel_updated else 'atlandı'}.",
                   "success")
    except Exception as e:
        flash(f"Stats hatası: {e}", "error")
    return redirect(url_for("channel_edit.edit", slug=slug))
