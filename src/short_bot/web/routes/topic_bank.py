"""Kanıtlanmış-konu bankası paneli: listele / YouTube API'den yenile / reddet.

Yenileme daemon thread'de koşar; istek hemen döner, sonuç loglanır (YouTube
API ile genellikle <1 dk).
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

    Madenci bedava 10K birim × anahtar kotasıyla saniyeler içinde biter;
    anahtar yoksa rota net hatayla durur (NexLev kaldırıldı)."""
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
            "keywords": list(getattr(cfg, "keywords", None) or []),
            "reference_channels": list(getattr(cfg, "reference_channels", None) or [])}


@bp.post("/channels/<slug>/topic-bank/refresh")
def refresh(slug):
    cfg = _load_cfg(slug)
    niche_query = (cfg.generator.topic if cfg.generator else "") or cfg.name
    db_path = current_app.config["SHORTBOT_DB_PATH"]
    language = cfg.language
    miner_kw = _miner_kwargs(cfg)
    if not miner_kw["api_keys"]:
        # NexLev kaldırıldı — tek backend YouTube API; anahtar yoksa iş başlatma.
        flash("YouTube API anahtarı yok — Ayarlar → YouTube Data API bölümünden "
              "anahtar ekleyin.", "error")
        return redirect(url_for("topic_bank.page", slug=slug))

    def _job():
        try:
            eng = init_db(db_path)
            res = refresh_topic_bank(eng, slug, niche_query,
                                     language=language, **miner_kw)
            _LOG.info(f"[topic-bank] {slug}: +{res['added']} "
                      f"(dup atlanan {res['skipped_dup']})")
        except Exception as e:  # noqa: BLE001 — thread paneli düşürmesin
            _LOG.warning(f"[topic-bank] {slug} yenileme hatası: {e}")

    _start_thread(_job)
    flash("Konu bankası yenileme başlatıldı — YouTube API ile genellikle 1 dk "
          "içinde biter; sayfayı sonra yenileyin.", "info")
    return redirect(url_for("topic_bank.page", slug=slug))


@bp.post("/channels/<slug>/topic-bank/<int:topic_id>/produce")
def produce(slug, topic_id):
    """Bankadaki BU konudan video üret.

    Normal üretimde başlığı LLM seçer (bankadan ilham alarak). Burada seçim
    kullanıcınındır: konu ZORLANIR, rotasyon ve tekrar-denetimi devre dışı kalır.
    """
    from short_bot.web.runs import launch_pipeline
    cfg = _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    row = next((r for r in all_bank_topics(eng, slug) if int(r["id"]) == topic_id), None)
    if row is None:
        abort(404)
    launch_pipeline(
        channel=cfg,
        settings=current_app.config["SHORTBOT_SETTINGS"],
        db_path=current_app.config["SHORTBOT_DB_PATH"],
        music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
        templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
        cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
        lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
        logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
        trigger="manual",
        forced_topic=row["topic"],
    )
    flash(f"'{str(row['topic'])[:60]}' konusundan üretim başladı (arka planda, ~10 dk).",
          "success")
    return redirect(url_for("topic_bank.page", slug=slug))


@bp.post("/channels/<slug>/topic-bank/<int:topic_id>/reject")
def reject(slug, topic_id):
    _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    reject_bank_topic(eng, topic_id)
    return redirect(url_for("topic_bank.page", slug=slug))


@bp.post("/channels/<slug>/topic-bank/refs")
def save_refs(slug):
    """Referans/rakip kanal listesini kanal YAML'ına yazar (her satır bir kanal)."""
    import dataclasses

    from flask import request

    from short_bot.config import save_channel
    cfg = _load_cfg(slug)
    raw = request.form.get("reference_channels", "")
    refs, seen = [], set()
    for line in raw.splitlines():
        s = line.strip()
        if s and s not in seen:
            seen.add(s); refs.append(s)
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    save_channel(path, dataclasses.replace(cfg, reference_channels=refs))
    flash(f"Referans kanallar kaydedildi ({len(refs)} kanal). Yenile'ye basınca "
          f"öncelikle bu kanalların patlamaları madenlenecek.", "info")
    return redirect(url_for("topic_bank.page", slug=slug))
