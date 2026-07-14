"""APScheduler wiring — registers cron jobs from channel YAMLs."""
import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from short_bot.config import list_channels, load_channel
from short_bot.db import init_db
from short_bot.dna_cache import cleanup_expired_dna_cache

_LOG = logging.getLogger(__name__)


def channel_cron_enabled(cfg) -> bool:
    """Kanalın schedule_cron'u kaydedilmeli mi?

    AUTOPILOT AÇIKSA HAYIR. Autopilot kendi slot'larından üretiyor; cron da koşarsa
    günde 3 yerine 6 video çıkar. Bu çifte üretim HİÇBİR HATA VERMEZ — yalnız kotayı
    ve kredileri yakar, üstelik slot'suz videolar pipeline tarafından ANINDA (public)
    yüklenip autopilot'un zamanlamasını bozar.
    """
    if not getattr(cfg, "schedule_cron", ""):
        return False
    ap = getattr(cfg, "autopilot", None)
    return not (ap is not None and ap.enabled)


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
            # AUTOPILOT AÇIKSA CRON KAYDEDİLMEZ — bkz. channel_cron_enabled.
            if not channel_cron_enabled(cfg):
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

    def _trends_refresh():
        """Cron: refresh trend cache for every distinct region in use by
        trend-boost-enabled channels. Each source failure is absorbed; the
        scheduler keeps running."""
        try:
            from short_bot.locale import trend_region_for
            from short_bot.pexels import load_secrets as _ls
            from short_bot.trends.aggregator import refresh_trends

            settings = app.config["SHORTBOT_SETTINGS"]
            if not settings.trends.enabled:
                return
            cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
            cache_root = Path(app.config["SHORTBOT_CACHE_DIR"]) / "trends"
            secrets = _ls(Path(app.config["SHORTBOT_DB_PATH"]).parent
                          / "secrets.yaml")
            yt_key = secrets.get("youtube_api_key", "") or ""

            # Collect (region, sources) pairs from channels that opted in
            wanted: dict[str, set[str]] = {}
            for ch in list_channels(cfg_dir / "channels", enabled_only=True):
                tb = ch.trend_boost
                if tb is None or not tb.enabled:
                    continue
                region = tb.region_override or trend_region_for(ch.language)
                srcs = (set(tb.sources) if tb.sources
                        else set(settings.trends.default_sources))
                wanted.setdefault(region, set()).update(srcs)

            for region, srcs in wanted.items():
                try:
                    cache = refresh_trends(
                        region, sources=list(srcs),
                        youtube_api_key=yt_key, cache_dir=cache_root,
                    )
                    _LOG.info(f"[trends] refreshed {region}: "
                              f"{len(cache.items)} items ({','.join(srcs)})")
                except Exception as e:  # noqa: BLE001
                    _LOG.warning(f"[trends] refresh {region} failed: {e}")
        except Exception as e:  # noqa: BLE001 — cron must not crash
            _LOG.warning(f"[trends] refresh job failed: {e}")

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

    def _nightly_insights_refresh():
        """Daily cron at 04:00: recompute per-channel performance insights.

        Runs AFTER the YT stats refresh cron at 03:00 so the freshest snapshots
        are reflected in the aggregation. Best-effort: any single channel's
        failure does NOT abort the rest."""
        try:
            from short_bot.learning.aggregator import refresh_all_channels
            eng = init_db(app.config["SHORTBOT_DB_PATH"])
            results = refresh_all_channels(eng, lookback_days=30)
            _LOG.info(
                f"[insights] nightly refresh: "
                f"{', '.join(f'{k}={v}' for k, v in results.items()) or '(no channels)'}"
            )
        except Exception as e:  # noqa: BLE001 — cron must not crash
            _LOG.warning(f"[insights] nightly refresh failed: {e}")

    scheduler.add_job(
        _nightly_insights_refresh,
        trigger=CronTrigger(hour=4, minute=0),
        id="_insights_refresh",
        replace_existing=True,
    )

    def _weekly_topic_bank_refresh():
        """Pazartesi 05:00: generator'lı kanalların konu bankasını tazele.

        Yalnız `bank_last_refresh` 7 günden eski (ya da hiç yok) kanallar için
        YouTube API madenciliği koşar. Tek kanalın hatası kalanları durdurmaz."""
        try:
            import yaml
            from datetime import datetime, timedelta, timezone
            from short_bot.config import resolve_ai_call
            from short_bot.db import bank_last_refresh
            from short_bot.reel_relevance import derive_footage_anchor
            from short_bot.topic_miner import refresh_topic_bank
            from short_bot.yt_outliers import resolve_youtube_api_keys
            eng = init_db(app.config["SHORTBOT_DB_PATH"])
            cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
            settings = app.config["SHORTBOT_SETTINGS"]
            try:
                sp = app.config["SHORTBOT_SECRETS_PATH"]
                secrets = (yaml.safe_load(sp.read_text(encoding="utf-8"))
                           if sp.exists() else {}) or {}
            except Exception:
                secrets = {}
            api_keys = resolve_youtube_api_keys(secrets)
            if not api_keys:
                _LOG.info("[topic-bank] haftalık: YouTube API anahtarı yok — atlandı")
                return
            try:
                llm_call = resolve_ai_call(settings, secrets, "default")
            except Exception:
                llm_call = None
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            for cfg in list_channels(cfg_dir / "channels"):
                try:
                    if cfg.content_source != "generator" or cfg.generator is None:
                        continue
                    last = bank_last_refresh(eng, cfg.slug)
                    if last is not None:
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                        if last > cutoff:
                            continue
                    tmpl = getattr(getattr(cfg, "dna", None),
                                   "search_query_template", "") or ""
                    res = refresh_topic_bank(eng, cfg.slug, cfg.generator.topic,
                                             language=cfg.language,
                                             api_keys=api_keys,
                                             anchor=derive_footage_anchor(tmpl),
                                             llm_call=llm_call,
                                             keywords=list(cfg.keywords or []),
                                             reference_channels=list(
                                                 cfg.reference_channels or []))
                    _LOG.info(f"[topic-bank] haftalık {cfg.slug}: +{res['added']}")
                except Exception as e:  # noqa: BLE001
                    _LOG.warning(f"[topic-bank] haftalık {cfg.slug}: {e}")
        except Exception as e:  # noqa: BLE001 — cron must not crash
            _LOG.warning(f"[topic-bank] haftalık tazeleme hatası: {e}")

    scheduler.add_job(
        _weekly_topic_bank_refresh,
        trigger=CronTrigger(day_of_week="mon", hour=5, minute=0),
        id="_topic_bank_refresh",
        replace_existing=True,
    )

    # --- AUTOPILOT ---------------------------------------------------------
    def _autopilot_channels():
        cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
        for cfg in list_channels(cfg_dir / "channels", enabled_only=True):
            ap = getattr(cfg, "autopilot", None)
            if ap is not None and ap.enabled:
                yield cfg

    def _autopilot_plan():
        """Bugünün + yarının slotlarını yaz. İDEMPOTENT.

        Hem gece cron'unda hem UYGULAMA AÇILIŞINDA koşar: uygulama kapalıysa gece
        cron'u kaçar ve o gün TAMAMEN boş geçerdi.
        """
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        from short_bot.autopilot_runner import plan_channel
        try:
            eng = init_db(app.config["SHORTBOT_DB_PATH"])
            for cfg in _autopilot_channels():
                try:
                    bugun = _dt.now(ZoneInfo(cfg.autopilot.timezone)).date()
                    n = plan_channel(eng, cfg, today_local=bugun, days=2)
                    if n:
                        _LOG.info(f"[autopilot] {cfg.slug}: +{n} slot planlandı")
                except Exception as e:  # noqa: BLE001 — bir kanal ötekileri durdurmasın
                    _LOG.warning(f"[autopilot] {cfg.slug} planlama hatası: {e}")
        except Exception as e:  # noqa: BLE001 — cron ÇÖKMEMELİ
            _LOG.warning(f"[autopilot] planlama işi başarısız: {e}")

    def _autopilot_tick():
        from short_bot.autopilot_runner import tick
        from short_bot.web.autopilot_deps import build_deps
        try:
            eng = init_db(app.config["SHORTBOT_DB_PATH"])
            for cfg in _autopilot_channels():
                try:
                    tick(eng, cfg, build_deps(app, cfg))
                except Exception as e:  # noqa: BLE001
                    _LOG.warning(f"[autopilot] {cfg.slug} tick hatası: {e}")
        except Exception as e:  # noqa: BLE001 — cron ÇÖKMEMELİ
            _LOG.warning(f"[autopilot] tick işi başarısız: {e}")

    scheduler.add_job(_autopilot_plan, trigger=CronTrigger(hour=3, minute=30),
                      id="_autopilot_plan", replace_existing=True)
    scheduler.add_job(_autopilot_tick, "interval", minutes=5,
                      id="_autopilot_tick", replace_existing=True)
    # AÇILIŞTA da planla: gece cron'u kaçmış olabilir (uygulama kapalıydı).
    _autopilot_plan()
    # Trend cache refresh on the interval from settings.trends.refresh_minutes.
    # Default 60min keeps the cache well under the 90min freshness window
    # used by the pipeline (so inline refresh on stale cache is rare).
    _trend_minutes = app.config["SHORTBOT_SETTINGS"].trends.refresh_minutes
    scheduler.add_job(
        _trends_refresh, "interval",
        minutes=_trend_minutes, id="_trends_refresh",
        replace_existing=True, next_run_time=None,
    )

    scheduler.start()
    app.scheduler = scheduler
    return scheduler
