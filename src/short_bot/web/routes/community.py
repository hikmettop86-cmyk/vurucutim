"""/community/<slug> — community-tab post idea generator.

YouTube Data API does NOT permit creating community posts (read-only), so
this page generates 5 ready-to-paste drafts. The user clicks "Generate",
inspects the drafts, presses the per-draft Copy button, then pastes into
YouTube Studio's Community tab.
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.community import (
    fetch_recent_short_titles, suggest_community_posts,
)
from short_bot.config import load_channel, resolve_ai_call
from short_bot.db import init_db
from short_bot.locale import trend_region_for
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.trends.aggregator import load_trends_cache

bp = Blueprint("community", __name__)
_LOG = logging.getLogger(__name__)


def _yaml_path(slug: str) -> Path:
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"


def _load_trend_terms(channel) -> list[str]:
    """Read currently-cached trends for the channel's region (best effort)."""
    cache_dir = Path(current_app.config["SHORTBOT_CACHE_DIR"]) / "trends"
    region = trend_region_for(channel.language)
    cache = load_trends_cache(region, cache_dir)
    if cache is None:
        return []
    return [t.term for t in cache.items[:8]]


@bp.route("/community/<slug>")
def view(slug):
    p = _yaml_path(slug)
    if not p.exists():
        abort(404)
    cfg = load_channel(p)
    return render_template(
        "community.html.j2", cfg=cfg, drafts=None,
    )


@bp.route("/community/<slug>/generate", methods=["POST"])
def generate(slug):
    p = _yaml_path(slug)
    if not p.exists():
        abort(404)
    cfg = load_channel(p)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    recent = fetch_recent_short_titles(eng, slug, limit=8, days=14)
    trends = _load_trend_terms(cfg)
    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    secrets = _load_secrets(Path(secrets_path)) if secrets_path else {}
    call = resolve_ai_call(settings, secrets, "default")
    try:
        drafts = suggest_community_posts(
            cfg, recent_titles=recent, trend_terms=trends,
            claude_path=call.claude_path,
            model=call.model,
            backend=call.backend,
            api_key=call.api_key,
        )
    except Exception as e:  # noqa: BLE001
        _LOG.warning(f"[community] generate failed for {slug}: {e}")
        flash(f"Taslak üretilemedi: {e}", "error")
        return redirect(url_for("community.view", slug=slug))

    return render_template(
        "community.html.j2", cfg=cfg, drafts=drafts,
        recent=recent, trends=trends,
    )
