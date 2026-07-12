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


def _miner_kwargs(cfg) -> dict:
    """YouTube-API backend girdileri: çoklu anahtar + EN çıpa + damıtma LLM'i.

    Anahtar varsa madenci saniyeler içinde biter (bedava 10K birim × anahtar);
    yoksa/patlarsa NexLev CLI'ya düşer (refresh_topic_bank backend='auto')."""
    import yaml
    from short_bot.config import resolve_ai_call
    from short_bot.reel_relevance import derive_footage_anchor
    from short_bot.yt_outliers import resolve_youtube_api_keys
    try:
        sp = current_app.config["SHORTBOT_SECRETS_PATH"]
        secrets = yaml.safe_load(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    except Exception:
        secrets = {}
    secrets = secrets or {}
    settings = current_app.config["SHORTBOT_SETTINGS"]
    try:
        llm_call = resolve_ai_call(settings, secrets, "default")
    except Exception:
        llm_call = None
    tmpl = getattr(getattr(cfg, "dna", None), "search_query_template", "") or ""
    return {"api_keys": resolve_youtube_api_keys(secrets),
            "anchor": derive_footage_anchor(tmpl),
            "llm_call": llm_call,
            "keywords": list(getattr(cfg, "keywords", None) or [])}


@bp.post("/channels/<slug>/topic-bank/refresh")
def refresh(slug):
    cfg = _load_cfg(slug)
    niche_query = (cfg.generator.topic if cfg.generator else "") or cfg.name
    db_path = current_app.config["SHORTBOT_DB_PATH"]
    claude_path = current_app.config["SHORTBOT_SETTINGS"].claude_cli_path
    language = cfg.language
    miner_kw = _miner_kwargs(cfg)

    def _job():
        try:
            eng = init_db(db_path)
            res = refresh_topic_bank(eng, slug, niche_query,
                                     language=language, claude_path=claude_path,
                                     **miner_kw)
            _LOG.info(f"[topic-bank] {slug}: +{res['added']} "
                      f"(dup atlanan {res['skipped_dup']})")
        except Exception as e:  # noqa: BLE001 — thread paneli düşürmesin
            _LOG.warning(f"[topic-bank] {slug} yenileme hatası: {e}")

    _start_thread(_job)
    msg = ("Konu bankası yenileme başlatıldı — YouTube API ile genellikle 1 dk "
           "içinde biter; sayfayı sonra yenileyin."
           if miner_kw["api_keys"] else
           "Konu bankası yenileme başlatıldı — YouTube API anahtarı yok, NexLev "
           "sorgusu birkaç dakika sürebilir; sayfayı sonra yenileyin.")
    flash(msg, "info")
    return redirect(url_for("topic_bank.page", slug=slug))


@bp.post("/channels/<slug>/topic-bank/<int:topic_id>/reject")
def reject(slug, topic_id):
    _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    reject_bank_topic(eng, topic_id)
    return redirect(url_for("topic_bank.page", slug=slug))
