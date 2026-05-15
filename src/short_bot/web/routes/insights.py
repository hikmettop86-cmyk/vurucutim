"""/insights/<slug> view page — performance dashboard per channel.

Live: when the DB-cached insights row is older than `_FRESH_HOURS` (or
missing), the page recomputes inline before rendering. The "Şimdi yenile"
POST endpoint forces a recompute regardless of freshness.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.config import list_channels
from short_bot.db import (init_db, load_channel_insights,
                          load_channels_with_uploads, upsert_channel_insights)
from short_bot.learning.aggregator import compute_channel_insights

bp = Blueprint("insights", __name__)
_LOG = logging.getLogger(__name__)

_FRESH_HOURS = 24    # serve cached row if computed_at < this old


def _get_or_recompute(eng, slug: str, *, lookback_days: int) -> dict:
    """Cache-first read: when DB row is missing or stale, recompute inline.
    The recomputed dict is persisted so the next page load is instant."""
    cached = load_channel_insights(eng, slug)
    if cached is not None:
        meta = cached.get("_meta", {})
        ts = meta.get("computed_at")
        if ts:
            try:
                computed_at = datetime.fromisoformat(ts)
                if computed_at.tzinfo is None:
                    computed_at = computed_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - computed_at < timedelta(hours=_FRESH_HOURS):
                    return cached
            except ValueError:
                pass

    insights = compute_channel_insights(eng, slug, lookback_days=lookback_days)
    try:
        upsert_channel_insights(
            eng, channel=slug,
            sample_size=insights["sample_size"],
            data_json=json.dumps(insights, ensure_ascii=False),
        )
    except Exception as e:  # noqa: BLE001
        _LOG.warning(f"[insights] cache write failed for {slug}: {e}")
    insights["_meta"] = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": insights["sample_size"],
    }
    return insights


@bp.route("/insights")
def index():
    """List page — pick a channel."""
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    with_uploads = set(load_channels_with_uploads(eng))
    chans = []
    for ch in list_channels(cfg_dir / "channels", enabled_only=False):
        cached = load_channel_insights(eng, ch.slug)
        chans.append({
            "slug": ch.slug, "name": ch.name,
            "language": ch.language, "enabled": ch.enabled,
            "has_uploads": ch.slug in with_uploads,
            "sample_size": (cached.get("_meta", {}).get("sample_size", 0)
                             if cached else 0),
            "last_computed": (cached.get("_meta", {}).get("computed_at")
                              if cached else None),
        })
    return render_template("insights_index.html.j2", channels=chans)


@bp.route("/insights/<slug>")
def view(slug):
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    p = cfg_dir / "channels" / f"{slug}.yaml"
    if not p.exists():
        abort(404)
    from short_bot.config import load_channel
    cfg = load_channel(p)

    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    insights = _get_or_recompute(eng, slug, lookback_days=30)
    return render_template(
        "insights_channel.html.j2",
        cfg=cfg, insights=insights,
        fresh_hours=_FRESH_HOURS,
    )


@bp.route("/insights/<slug>/refresh", methods=["POST"])
def refresh(slug):
    """Force-recompute insights for this channel, ignoring cache freshness."""
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    p = cfg_dir / "channels" / f"{slug}.yaml"
    if not p.exists():
        abort(404)

    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    try:
        insights = compute_channel_insights(eng, slug, lookback_days=30)
        upsert_channel_insights(
            eng, channel=slug,
            sample_size=insights["sample_size"],
            data_json=json.dumps(insights, ensure_ascii=False),
        )
        flash(
            f"İçgörüler güncellendi (örnek sayısı: {insights['sample_size']}).",
            "success",
        )
    except Exception as e:  # noqa: BLE001
        flash(f"Hesaplama hatası: {e}", "error")
    return redirect(url_for("insights.view", slug=slug))
