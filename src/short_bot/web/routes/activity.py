"""Activity timeline page: 24h summary + live runs + chronological feed."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, render_template, request

from short_bot.db import init_db
from short_bot.web.activity import (
    ALL_TYPES, build_activity_events, compute_summary_24h, list_running_runs,
)

# Normal üretim 8-14 dk sürüyor (ölçüldü). Bunun üstünde çalışan bir koşu
# muhtemelen TAKILMIŞTIR: süreci ölen koşu DB'de sonsuza dek 'çalışıyor'
# kalır, çünkü kendini temizleyecek kimse yoktur.
STALE_RUN_AFTER_S = 20 * 60

bp = Blueprint("activity", __name__)


_SINCE_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _parse_filters():
    """Read filter args from request. Defaults: since=24h, no other filters."""
    channel = (request.args.get("channel") or "").strip() or None
    raw_type = (request.args.get("type") or "").strip()
    types = (raw_type,) if raw_type in ALL_TYPES else ALL_TYPES
    raw_status = (request.args.get("status") or "").strip()
    status = raw_status if raw_status in ("success", "failed", "no_candidates") else None
    since_key = (request.args.get("since") or "24h").strip()
    delta = _SINCE_WINDOWS.get(since_key, _SINCE_WINDOWS["24h"])
    since = datetime.now(timezone.utc) - delta
    cursor_raw = (request.args.get("cursor") or "").strip()
    cursor = None
    if cursor_raw:
        try:
            cursor = datetime.fromisoformat(cursor_raw)
        except ValueError:
            cursor = None
    return {
        "channel": channel,
        "types": types,
        "status": status,
        "since": since,
        "since_key": since_key,
        "cursor": cursor,
    }


@bp.route("/activity")
def view():
    """Full /activity page: summary + live runs + first feed page."""
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    f = _parse_filters()
    summary = compute_summary_24h(eng)
    running = list_running_runs(eng)
    events = build_activity_events(
        eng,
        since=f["since"], channel=f["channel"],
        types=f["types"], status=f["status"],
        limit=200, cursor=f["cursor"],
    )
    from short_bot.config import list_channels
    channels = list_channels(
        current_app.config["SHORTBOT_CONFIG_DIR"] / "channels", enabled_only=False,
    )
    return render_template(
        "activity.html.j2",
        summary=summary,
        running=running,
        stale_after_s=STALE_RUN_AFTER_S,
        events=events,
        channels=channels,
        f_channel=f["channel"] or "",
        f_type=request.args.get("type", "").strip(),
        f_status=request.args.get("status", "").strip(),
        f_since=f["since_key"],
    )


@bp.route("/activity/feed")
def feed_partial():
    """htmx partial: renders only the feed rows. Filters apply.

    Optional ?limit=N override (default 200) to support tests + future tuning.
    """
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    f = _parse_filters()
    try:
        limit = int(request.args.get("limit", "200"))
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 500))  # clamp
    events = build_activity_events(
        eng,
        since=f["since"], channel=f["channel"],
        types=f["types"], status=f["status"],
        limit=limit, cursor=f["cursor"],
    )
    has_filters = bool(
        f["channel"] or f["status"]
        or (f["types"] != ALL_TYPES)
        or (f["since_key"] != "24h")
    )
    next_cursor = events[-1].timestamp.isoformat() if len(events) >= limit else None
    return render_template(
        "_partials/activity_feed.html.j2",
        events=events,
        has_filters=has_filters,
        next_cursor=next_cursor,
        f_channel=f["channel"] or "",
        f_type=request.args.get("type", "").strip(),
        f_status=request.args.get("status", "").strip(),
        f_since=f["since_key"],
        limit=limit,
    )


@bp.route("/activity/live-runs")
def live_runs_partial():
    """htmx partial: renders only the live-runs section."""
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    running = list_running_runs(eng)
    return render_template("_partials/activity_live_runs.html.j2", running=running,
                           stale_after_s=STALE_RUN_AFTER_S)
