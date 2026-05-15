"""/trends view page: current cached trends per region + manual refresh."""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, url_for

from short_bot.config import list_channels
from short_bot.locale import trend_region_for
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.trends.aggregator import load_trends_cache, refresh_trends

bp = Blueprint("trends", __name__)
_LOG = logging.getLogger(__name__)


def _active_regions_and_sources() -> dict[str, set[str]]:
    """Aggregate (region -> sources) from every enabled channel with
    trend_boost.enabled. Channel sources override settings defaults; when
    a channel has no `sources` override we pull settings.trends.default_sources.
    """
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    settings = current_app.config["SHORTBOT_SETTINGS"]
    default_sources = set(settings.trends.default_sources)

    out: dict[str, set[str]] = {}
    for ch in list_channels(cfg_dir / "channels", enabled_only=True):
        tb = ch.trend_boost
        if tb is None or not tb.enabled:
            continue
        region = tb.region_override or trend_region_for(ch.language)
        srcs = set(tb.sources) if tb.sources else set(default_sources)
        out.setdefault(region, set()).update(srcs)
    return out


@bp.route("/trends")
def view():
    settings = current_app.config["SHORTBOT_SETTINGS"]
    cache_dir = Path(current_app.config["SHORTBOT_CACHE_DIR"]) / "trends"
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]

    active = _active_regions_and_sources()

    # Build per-region cache snapshot for the template.
    regions = []
    for region, srcs in sorted(active.items()):
        cache = load_trends_cache(region, cache_dir)
        regions.append({
            "region": region,
            "sources_wanted": sorted(srcs),
            "cache": cache,        # None when no cache file yet
        })

    # All enabled channels (for the "which channels use trends" table)
    channels = []
    for ch in list_channels(cfg_dir / "channels", enabled_only=False):
        tb = ch.trend_boost
        channels.append({
            "slug": ch.slug, "name": ch.name, "language": ch.language,
            "enabled": ch.enabled,
            "tb_enabled": bool(tb and tb.enabled),
            "tb_max_boost": (tb.max_boost if tb else None),
            "tb_region": ((tb.region_override if tb and tb.region_override
                            else trend_region_for(ch.language))),
            "tb_sources": (list(tb.sources) if tb and tb.sources
                           else (list(settings.trends.default_sources)
                                 if tb and tb.enabled else [])),
        })

    return render_template(
        "trends.html.j2",
        settings_enabled=settings.trends.enabled,
        refresh_minutes=settings.trends.refresh_minutes,
        cache_max_age_minutes=settings.trends.cache_max_age_minutes,
        regions=regions,
        channels=channels,
    )


@bp.route("/trends/refresh", methods=["POST"])
def refresh():
    """Manual 'refresh now' button — fetches every active region's trends
    inline, persists cache. Best-effort: a failure on one region doesn't
    abort the others."""
    settings = current_app.config["SHORTBOT_SETTINGS"]
    if not settings.trends.enabled:
        flash("Trend Detection kapali (Ayarlar > Trend Detection > Etkin).", "error")
        return redirect(url_for("trends.view"))

    cache_dir = Path(current_app.config["SHORTBOT_CACHE_DIR"]) / "trends"
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    yt_key = ""
    if secrets_path:
        secrets = _load_secrets(Path(secrets_path))
        yt_key = secrets.get("youtube_api_key", "") or ""

    active = _active_regions_and_sources()
    if not active:
        flash("Hicbir kanalda trend_boost.enabled=true yok. Once bir kanalda ac.",
              "error")
        return redirect(url_for("trends.view"))

    ok, fail = 0, 0
    for region, srcs in active.items():
        try:
            cache = refresh_trends(
                region, sources=sorted(srcs),
                youtube_api_key=yt_key, cache_dir=cache_dir,
            )
            _LOG.info(f"[trends/manual] {region}: {len(cache.items)} terms")
            ok += 1
        except Exception as e:  # noqa: BLE001
            _LOG.warning(f"[trends/manual] {region} failed: {e}")
            fail += 1

    if fail == 0:
        flash(f"{ok} bolge icin trendler yenilendi.", "success")
    else:
        flash(f"{ok} bolge yenilendi, {fail} basarisiz oldu (loglara bak).",
              "error" if ok == 0 else "warning")
    return redirect(url_for("trends.view"))
