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
from short_bot.db import (all_bank_topics, init_db, mark_bank_topic_used,
                          reject_bank_topic)
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
    """YALNIZ aktif konular listelenir.

    Üretilmiş ('used') ve reddedilmiş konular DB'DE KALIR — mükerrer üretimi asıl
    engelleyen şey odur (üretim prompt'u yalnız aktif kayıtları görür). Ama listede
    durmalarının bir faydası yok: kullanıcı onlara yanlışlıkla basıp aynı videoyu
    ikinci kez üretebiliyordu.
    """
    from short_bot.topic_autofill import LOW_WATER
    cfg = _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    rows = [r for r in all_bank_topics(eng, slug) if r["status"] == "active"]
    return render_template("topic_bank.html.j2", slug=slug, channel=cfg, rows=rows,
                           low_water=LOW_WATER)


def _secrets() -> dict:
    import yaml
    try:
        sp = current_app.config["SHORTBOT_SECRETS_PATH"]
        return (yaml.safe_load(sp.read_text(encoding="utf-8"))
                if sp.exists() else {}) or {}
    except Exception:   # noqa: BLE001
        return {}


def _sonnet():
    """Konu üretimi ve doğrulaması SONNET 5 ile koşar (Claude CLI → OpenRouter).

    ÖLÇÜLDÜ: damıtma eskiden role='default' ile koşuyordu = google/gemini-3.1-flash-lite,
    sistemin EN UCUZ modeli. Bankanın %85'i çöp oldu (27 aktif konudan 23'ü) ve bazıları
    bilimsel olarak YANLIŞTI. Kanalın otoritesi ürünüdür.
    """
    from short_bot.llm_sonnet import sonnet_json
    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets = _secrets()

    def _f(prompt, schema, **kw):
        return sonnet_json(prompt, schema,
                           claude_path=settings.claude_cli_path,
                           openrouter_model=settings.openrouter_models.get(
                               "script", "anthropic/claude-sonnet-5"),
                           openrouter_key=secrets.get("openrouter_api_key"))
    return _f


def _miner_kwargs(cfg) -> dict:
    """Kanıt madenciliği girdileri.

    ``api_keys`` ARTIK ZORUNLU DEĞİL: anahtar yoksa madencilik atlanır ve konu kanıtsız
    üretilir (bkz. topic_propose). ``llm_call`` yalnız arama SORGUSU üretimi için
    (ucuz model yeter); konuyu YAZAN model ``llm`` (Sonnet 5).
    """
    from short_bot.config import resolve_ai_call
    from short_bot.reel_relevance import derive_footage_anchor
    from short_bot.yt_outliers import resolve_youtube_api_keys
    secrets = _secrets()
    settings = current_app.config["SHORTBOT_SETTINGS"]
    try:
        llm_call = resolve_ai_call(settings, secrets, "default")
    except Exception:   # noqa: BLE001
        llm_call = None
    tmpl = getattr(getattr(cfg, "dna", None), "search_query_template", "") or ""
    from short_bot.persona import channel_topic_guidance
    return {"api_keys": resolve_youtube_api_keys(secrets),
            "anchor": derive_footage_anchor(tmpl),
            "llm_call": llm_call,
            "llm": _sonnet(),
            "keywords": list(getattr(cfg, "keywords", None) or []),
            "reference_channels": list(getattr(cfg, "reference_channels", None) or []),
            "extra_guidance": channel_topic_guidance(
                getattr(getattr(cfg, "reel", None), "persona", ""), cfg.language)}


@bp.post("/channels/<slug>/topic-bank/refresh")
def refresh(slug):
    cfg = _load_cfg(slug)
    niche_query = (cfg.generator.topic if cfg.generator else "") or cfg.name
    db_path = current_app.config["SHORTBOT_DB_PATH"]
    language = cfg.language
    miner_kw = _miner_kwargs(cfg)
    anahtarsiz = not miner_kw["api_keys"]

    def _job():
        try:
            eng = init_db(db_path)
            res = refresh_topic_bank(eng, slug, niche_query,
                                     language=language, **miner_kw)
            _LOG.info(f"[topic-bank] {slug}: +{res['added']} konu "
                      f"({res['skipped_dup']} mükerrer, "
                      f"{res['rejected']} doğrulamada elendi)")
        except Exception as e:  # noqa: BLE001 — thread paneli düşürmesin
            _LOG.warning(f"[topic-bank] {slug} yenileme hatası: {e}")

    _start_thread(_job)
    if anahtarsiz:
        # ARTIK HATA DEĞİL: anahtar yoksa kanıt toplanmaz ama konu yine üretilir.
        flash("YouTube API anahtarı yok — konular KANIT OLMADAN üretiliyor (model "
              "kendi bilgisiyle). Kanıtlı konu için Ayarlar → YouTube Data API'den "
              "anahtar ekleyin.", "info")
    else:
        flash("Konu bankası yenileniyor — birkaç dakika sürer; sayfayı sonra "
              "yenileyin.", "info")
    return redirect(url_for("topic_bank.page", slug=slug))


@bp.post("/channels/<slug>/topic-bank/audit")
def audit(slug):
    """Bankayı denetle: içi boş / vaat eden / bilimsel olarak yanlış konuları reddet.

    SENKRON. Denetim tek LLM çağrısı ve kullanıcı sonucu ANINDA görmeli ("kaç konu
    elendi"). "Birkaç dakika içinde biter" diyen bir panel, sonucu asla göstermez —
    aynı yalanı autopilot planlayıcısında yaşadık ve düzelttik.
    """
    from short_bot.topic_audit import audit_bank
    cfg = _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    try:
        res = audit_bank(eng, slug, language=cfg.language, llm=_sonnet())
    except Exception as e:   # noqa: BLE001 — kullanıcıya SEBEBİ söyle
        flash(f"Denetim başarısız: {e}", "error")
        return redirect(url_for("topic_bank.page", slug=slug))
    flash(f"{res['checked']} konu denetlendi, {res['rejected']} tanesi reddedildi "
          f"(içi boş / vaat eden / bilimsel olarak yanlış).", "success")
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
    if row is None or row["status"] != "active":
        abort(404)
    # ÜRETİME VERİLEN KONU ANINDA 'used' — aksi hâlde kullanıcı (ya da LLM, banka
    # prompt'u aktif kayıtları görüyor) aynı konuyu ikinci kez üretebilirdi.
    mark_bank_topic_used(eng, topic_id)
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
