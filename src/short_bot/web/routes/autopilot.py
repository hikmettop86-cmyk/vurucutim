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

    # SESSİZ BOZULMA UYARILARI. İkisi de gerçek: otomasyon "açık" görünür ama hiçbir
    # şey olmaz, ve kullanıcı nedenini asla öğrenemez. Otomasyon kendini AÇIKLAMALI.
    from short_bot.autopilot_runner import upload_enabled
    uyarilar = []
    if ap and ap.enabled and not getattr(cfg, "enabled", True):
        uyarilar.append(
            "Kanal DEVRE DIŞI — hiçbir slot planlanmayacak ve hiçbir video "
            "üretilmeyecek. Kanalı Ayarlar'dan etkinleştir.")
    if ap and ap.enabled and not upload_enabled(cfg):
        uyarilar.append(
            "YouTube otomatik yükleme KAPALI — videolar üretilecek ama "
            "yüklenmeyecek (slot 'üretildi'de kalır, elle yüklersin). "
            "Otomatik yükleme istiyorsan Ayarlar → YouTube'dan aç.")

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
