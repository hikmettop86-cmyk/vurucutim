"""APScheduler wiring — registers cron jobs from channel YAMLs."""
import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from short_bot.config import list_channels, load_channel
from short_bot.db import init_db
from short_bot.dna_cache import cleanup_expired_dna_cache

_LOG = logging.getLogger(__name__)


def init_scheduler(app):
    # job_defaults:
    # - misfire_grace_time=3600: Eger VurucuTim restart oldu (update vb.) ve fire
    #   zamanini 1 saatten az gecirdiyse, fire'i hala tetikle. Default 1sn cok kati.
    # - coalesce=True: Ust uste kacirilmis fire'lari TEK fire'a birlestir (10 saat
    #   kapali kalmis ise 3 fire'i birden tetiklemez, 1 kez calisir).
    # 'Cron'lar calismiyor' / 'gun boyu yuklememis' sikayetlerinin kok sebebi.
    scheduler = BackgroundScheduler(job_defaults={
        "misfire_grace_time": 3600,
        "coalesce": True,
    })

    def _run_for_channel(slug: str):
        from short_bot.web.runs import launch_pipeline
        cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
        cfg = load_channel(cfg_dir / "channels" / f"{slug}.yaml")
        settings = app.config["SHORTBOT_SETTINGS"]
        launch_pipeline(
            channel=cfg, settings=settings,
            db_path=app.config["SHORTBOT_DB_PATH"],
            music_root=app.config["SHORTBOT_MUSIC_ROOT"],
            templates_dir=app.config["SHORTBOT_TEMPLATES_DIR"],
            cache_dir=app.config["SHORTBOT_CACHE_DIR"],
            lock_dir=app.config["SHORTBOT_LOCK_DIR"],
            logs_dir=app.config["SHORTBOT_LOGS_DIR"],
            trigger="cron",
        )

    def _reload_jobs():
        cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
        # Remove all per-channel jobs (keep _reload_jobs)
        for job in list(scheduler.get_jobs()):
            if job.id != "_reload_jobs":
                scheduler.remove_job(job.id)
        for cfg in list_channels(cfg_dir / "channels", enabled_only=True):
            if not cfg.schedule_cron:
                continue
            try:
                trigger = CronTrigger.from_crontab(cfg.schedule_cron)
            except ValueError:
                continue  # invalid cron, skip
            scheduler.add_job(
                _run_for_channel, trigger,
                args=[cfg.slug], id=cfg.slug,
                max_instances=1, replace_existing=True,
            )

    def _daily_dna_cache_cleanup():
        """Daily cron: delete dna_cache rows older than 90 days + their CSS files."""
        try:
            eng = init_db(app.config["SHORTBOT_DB_PATH"])
            css_dir = Path(app.config["SHORTBOT_TEMPLATES_DIR"]) / "css"
            n = cleanup_expired_dna_cache(eng, css_dir, days=90)
            if n > 0:
                _LOG.info(f"[dna_cache] daily cleanup: deleted {n} expired entries")
        except Exception as e:  # noqa: BLE001 — cron must not crash
            _LOG.warning(f"[dna_cache] daily cleanup failed: {e}")

    # Initial register
    _reload_jobs()
    # Re-scan channel configs every 5 minutes
    scheduler.add_job(_reload_jobs, "interval", minutes=5, id="_reload_jobs")
    # Daily DNA cache cleanup at 03:15
    scheduler.add_job(
        _daily_dna_cache_cleanup,
        trigger=CronTrigger(hour=3, minute=15),
        id="_dna_cache_cleanup",
        replace_existing=True,
    )

    scheduler.start()
    app.scheduler = scheduler
    return scheduler
