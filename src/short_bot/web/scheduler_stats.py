"""Daily YouTube stats refresh job, scheduled via APScheduler."""
import logging
from pathlib import Path

from short_bot.config import list_channels
from short_bot.db import init_db
from short_bot.youtube.stats_refresh import refresh_channel_stats


_log = logging.getLogger("short_bot.web.scheduler_stats")


def refresh_all_channels_stats(*, config_dir: Path, db_path: Path,
                                yt_creds_root: Path) -> None:
    """Iterate all enabled channels, refresh each. Per-channel errors logged
    but don't stop the rest."""
    eng = init_db(db_path)
    try:
        channels = list_channels(config_dir / "channels", enabled_only=True)
    except Exception as e:
        _log.exception("scheduler_stats: failed to list channels: %s", e)
        return
    for ch in channels:
        try:
            from short_bot.youtube import auth as _yt_auth
            result = refresh_channel_stats(
                eng=eng, channel_slug=ch.slug, yt_creds_root=yt_creds_root,
                video_lookback_days=30, creds_slug=_yt_auth.creds_slug(ch),
            )
            _log.info("[YT stats] %s: %d videos, channel=%s, %d arama terimi, %s",
                       ch.slug, result.video_count,
                       "updated" if result.channel_updated else "skipped",
                       result.search_terms, result.skipped_reason or "ok")
        except Exception:
            _log.exception("[YT stats] %s: failed", ch.slug)


def init_stats_scheduler(app):
    """Wire APScheduler cron at 03:00 daily."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        refresh_all_channels_stats,
        CronTrigger(hour=3, minute=0),
        kwargs={
            "config_dir": app.config["SHORTBOT_CONFIG_DIR"],
            "db_path": app.config["SHORTBOT_DB_PATH"],
            "yt_creds_root": app.config["SHORTBOT_YT_CREDS_DIR"],
        },
        id="yt-stats-daily",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
