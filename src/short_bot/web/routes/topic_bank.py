"""Kanıtlanmış-konu bankası paneli: listele / NexLev'den yenile / reddet.

Yenileme daemon thread'de koşar (Storyblocks connect deseni) — NexLev claude-CLI
köprüsü dakikalar sürebilir; istek hemen döner, sonuç loglanır.
"""
from __future__ import annotations

import logging
import threading

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, url_for)

from short_bot.config import load_channel
from short_bot.db import all_bank_topics, init_db, reject_bank_topic
from short_bot.topic_miner import refresh_topic_bank

bp = Blueprint("topic_bank", __name__)
_LOG = logging.getLogger(__name__)


def _start_thread(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _load_cfg(slug: str):
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    return load_channel(path)


@bp.get("/channels/<slug>/topic-bank")
def page(slug):
    cfg = _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    rows = all_bank_topics(eng, slug)
    return render_template("topic_bank.html.j2", slug=slug, channel=cfg, rows=rows)


@bp.post("/channels/<slug>/topic-bank/refresh")
def refresh(slug):
    cfg = _load_cfg(slug)
    niche_query = (cfg.generator.topic if cfg.generator else "") or cfg.name
    db_path = current_app.config["SHORTBOT_DB_PATH"]
    claude_path = current_app.config["SHORTBOT_SETTINGS"].claude_cli_path
    language = cfg.language

    def _job():
        try:
            eng = init_db(db_path)
            res = refresh_topic_bank(eng, slug, niche_query,
                                     language=language, claude_path=claude_path)
            _LOG.info(f"[topic-bank] {slug}: +{res['added']} "
                      f"(dup atlanan {res['skipped_dup']})")
        except Exception as e:  # noqa: BLE001 — thread paneli düşürmesin
            _LOG.warning(f"[topic-bank] {slug} yenileme hatası: {e}")

    _start_thread(_job)
    flash("Konu bankası yenileme başlatıldı — NexLev sorgusu birkaç dakika "
          "sürebilir; sayfayı sonra yenileyin.", "info")
    return redirect(url_for("topic_bank.page", slug=slug))


@bp.post("/channels/<slug>/topic-bank/<int:topic_id>/reject")
def reject(slug, topic_id):
    _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    reject_bank_topic(eng, topic_id)
    return redirect(url_for("topic_bank.page", slug=slug))
