"""Otomasyon paneli: slotlar GÖRÜNÜR olsun.

Görünmeyen bir otomasyon, güvenilemeyen bir otomasyondur. Kullanıcı tek bakışta
görmeli: bugün kaç video, hangi saatlerde, hangisi patladı ve NEDEN.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, url_for)

from short_bot.config import AutopilotConfig, load_channel, save_channel
from short_bot.db import init_db, slots_in_range

bp = Blueprint("autopilot", __name__)


def _load_cfg(slug: str):
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    return load_channel(path)


def _save(cfg, slug: str, ap: AutopilotConfig) -> None:
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    save_channel(path, dataclasses.replace(cfg, autopilot=ap))


@bp.get("/channels/<slug>/autopilot")
def page(slug):
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])

    tz = ZoneInfo(ap.timezone) if ap else ZoneInfo("Europe/Istanbul")
    bugun = datetime.now(tz).date()
    yarin = bugun + timedelta(days=1)
    rows = slots_in_range(eng, slug, bugun.isoformat(), yarin.isoformat())

    def _yerel(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)   # DB'ye UTC yazıyoruz
        return dt.astimezone(tz)

    gunler: dict[str, list] = {}
    for r in rows:
        r["local_time"] = _yerel(r["slot_at_utc"])
        gunler.setdefault(r["slot_local_date"], []).append(r)

    bugunku = gunler.get(bugun.isoformat(), [])
    ozet = {
        "toplam": len(bugunku),
        "published": sum(1 for x in bugunku if x["status"] == "published"),
        "scheduled": sum(1 for x in bugunku if x["status"] == "scheduled"),
        "failed": sum(1 for x in bugunku if x["status"] in ("failed", "skipped")),
    }

    # SESSİZ BOZULMA UYARILARI — ve ÇÖZÜM DÜĞMELERİ.
    #
    # İkisi de gerçek: otomasyon "açık" görünür ama hiçbir şey olmaz, ve kullanıcı
    # nedenini asla öğrenemez. Ama SÖYLEMEK yetmez: "Ayarlar'dan etkinleştir" demek
    # kullanıcıyı başka bir sayfaya yollamaktır. Sorunu GÖRDÜĞÜ yerde çözebilmeli.
    from short_bot.autopilot_runner import upload_enabled
    uyarilar = []
    if ap and ap.enabled and not getattr(cfg, "enabled", True):
        uyarilar.append({
            "text": "Kanal DEVRE DIŞI — hiçbir slot planlanmayacak ve hiçbir video "
                    "üretilmeyecek.",
            "action": f"/channels/{slug}/autopilot/enable-channel",
            "label": "Kanalı etkinleştir",
            # ÜRETİM VE YÜKLEME GERÇEKTEN BAŞLAR — kullanıcı ne olacağını bilmeli.
            "confirm": (f"Kanal etkinleşecek ve otomasyon çalışmaya başlayacak: "
                        f"günde {ap.daily_count} video üretilecek"
                        + (", YouTube'a yüklenecek ve yayınlanacak."
                           if upload_enabled(cfg) else " (yükleme kapalı).")
                        + " ai33 kredisi, LLM çağrısı ve YouTube kotası harcanacak. "
                          "Devam edilsin mi?"),
        })
    if ap and ap.enabled and not upload_enabled(cfg):
        uyarilar.append({
            "text": "YouTube otomatik yükleme KAPALI — videolar üretilecek ama "
                    "yüklenmeyecek (slot 'üretildi'de kalır, elle yüklersin).",
            "action": f"/channels/{slug}/autopilot/enable-upload",
            "label": "Otomatik yüklemeyi aç",
            "confirm": ("Üretilen videolar YouTube'a otomatik yüklenecek ve "
                        "planlanan saatte YAYINLANACAK. Devam edilsin mi?"),
        })

    return render_template("autopilot.html.j2", slug=slug, channel=cfg,
                           enabled=bool(ap and ap.enabled), ap=ap,
                           today=bugun.isoformat(), tomorrow=yarin.isoformat(),
                           days=gunler, summary=ozet, tz=str(tz),
                           warnings=uyarilar)


@bp.post("/channels/<slug>/autopilot/enable")
def enable(slug):
    """Otomasyonu aç. Slotlar bir sonraki planlama turunda yazılır."""
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None) or AutopilotConfig()
    _save(cfg, slug, ap.model_copy(update={"enabled": True}))
    flash("Otomasyon açıldı. Slotlar birkaç dakika içinde planlanacak. "
          "Kanalın normal cron'u artık koşmayacak (çifte üretim olmasın diye).",
          "success")
    return redirect(url_for("autopilot.page", slug=slug))


@bp.post("/channels/<slug>/autopilot/disable")
def disable(slug):
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None) or AutopilotConfig()
    _save(cfg, slug, ap.model_copy(update={"enabled": False}))
    flash("Otomasyon kapatıldı. Kanalın normal cron'u yeniden devreye girdi.", "info")
    return redirect(url_for("autopilot.page", slug=slug))


@bp.post("/channels/<slug>/autopilot/enable-channel")
def enable_channel(slug):
    """Kanalı etkinleştir — otomasyon sayfasından, sorunu gördüğün yerden.

    Eskiden uyarı "Ayarlar'dan etkinleştir" diyordu: kullanıcıyı başka bir sayfaya
    yolluyordu. Sorunu gösteren sayfa, çözümü de sunmalı.
    """
    cfg = _load_cfg(slug)
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    save_channel(path, dataclasses.replace(cfg, enabled=True))
    flash("Kanal etkinleştirildi. Slotlar birkaç dakika içinde planlanacak ve "
          "otomasyon çalışmaya başlayacak.", "success")
    return redirect(url_for("autopilot.page", slug=slug))


@bp.post("/channels/<slug>/autopilot/enable-upload")
def enable_upload(slug):
    """YouTube otomatik yüklemeyi aç.

    KULLANICININ AYARI SON SÖZ: autopilot bu bayrağı es geçemez (bkz.
    autopilot_runner.upload_enabled). Açmak da yalnız kullanıcının işidir.
    """
    from short_bot.config import YoutubeChannelConfig
    cfg = _load_cfg(slug)
    yt = getattr(cfg, "youtube", None) or YoutubeChannelConfig()
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    save_channel(path, dataclasses.replace(
        cfg, youtube=yt.model_copy(update={"auto_upload": True})))
    flash("YouTube otomatik yükleme açıldı. Üretilen videolar planlanan saatte "
          "yayınlanacak.", "success")
    return redirect(url_for("autopilot.page", slug=slug))
