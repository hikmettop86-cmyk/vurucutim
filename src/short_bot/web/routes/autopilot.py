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


def _plan_now(slug: str) -> int:
    """Slotları HEMEN planla — bir sonraki tick'i (5 dk) bile bekletme.

    GERÇEK HATA: planlama yalnız açılışta ve gece 03:30'da koşuyordu. Kullanıcı
    otomasyonu açtığında slotlar SABAH 03:30'A KADAR yazılmıyordu; panel ise
    "birkaç dakika içinde planlanacak" diyordu. Ayarı değiştiren kişi sonucunu
    ANINDA görmeli, yoksa "çalışmıyor" der ve haklı olur.
    """
    from datetime import datetime as _dt

    from short_bot.autopilot_runner import plan_channel
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None)
    if ap is None or not ap.enabled:
        return 0
    try:
        eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
        bugun = _dt.now(ZoneInfo(ap.timezone)).date()
        return plan_channel(eng, cfg, today_local=bugun, days=2)
    except Exception:   # noqa: BLE001 — planlama tick'te de denenecek
        return 0


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

    # KONU BANKASI SU SEVİYESİ. Otomasyon günde ~2-3 konu tüketiyor. Banka kuruyunca
    # üretim DURMAZ ama SESSİZCE BOZULUR: seri durur (ark için tohum yok), bağımsız
    # videolar kanıtlanmış konu olmadan üretilir. Bunu görmeden fark edemezsin.
    if ap and ap.enabled and cfg.content_source == "generator":
        from short_bot.db import active_bank_count
        from short_bot.topic_autofill import LOW_WATER
        kalan = active_bank_count(eng, slug)
        gunluk = max(1, ap.daily_count - ap.series_per_day) + \
            (1 if ap.series_per_day else 0)
        if kalan < LOW_WATER:
            uyarilar.append({
                "text": f"KONU BANKASI AZALDI — {kalan} aktif konu kaldı "
                        f"(günde ~{gunluk} tüketiliyor, yani ~{kalan // max(1, gunluk)} gün). "
                        f"Sistem 4 saatte bir otomatik doldurmaya çalışıyor; yine de "
                        f"azalıyorsa Konu Bankası'na REFERANS KANAL ekleyin.",
                "action": f"/channels/{slug}/topic-bank/refresh",
                "label": "Şimdi yenile",
                "confirm": "Konu bankası şimdi yenilensin mi? (YouTube API kotası "
                           "harcanır, ~1 dakika)",
            })

    return render_template("autopilot.html.j2", slug=slug, channel=cfg,
                           enabled=bool(ap and ap.enabled), ap=ap,
                           today=bugun.isoformat(), tomorrow=yarin.isoformat(),
                           days=gunler, summary=ozet, tz=str(tz),
                           warnings=uyarilar)


@bp.post("/channels/<slug>/autopilot/settings")
def settings(slug):
    """Otomasyon ayarları — BURADA, otomasyon sayfasında.

    Kullanıcı şikâyeti: "günde kaç video yükleneceği ayarı arayüzde yok". Ayarı
    Ayarlar sayfasına gömmek, otomasyonu izlediğin yerden ayırmak demekti.
    """
    from flask import request
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None) or AutopilotConfig()

    def _int(name, fb):
        try:
            return int(request.form.get(name, fb))
        except (TypeError, ValueError):
            return fb

    lo = _int("active_lo", ap.active_hours[0])
    hi = _int("active_hi", ap.active_hours[1])
    guncel = {
        "daily_count": _int("daily_count", ap.daily_count),
        "series_per_day": _int("series_per_day", ap.series_per_day),
        "active_hours": (lo, hi),
        "produce_lead_hours": _int("produce_lead_hours", ap.produce_lead_hours),
        "jitter_minutes": _int("jitter_minutes", ap.jitter_minutes),
        "publish_mode": request.form.get("publish_mode", ap.publish_mode),
    }
    try:
        yeni = ap.model_copy(update=guncel)
        AutopilotConfig.model_validate(yeni.model_dump())   # doğrulamayı ZORLA
    except Exception as e:   # noqa: BLE001 — pydantic ValidationError vb.
        flash(f"Ayarlar geçersiz: {e}", "error")
        return redirect(url_for("autopilot.page", slug=slug))

    _save(cfg, slug, yeni)
    # SLOT SAYISI/TÜRÜ DEĞİŞTİYSE gelecek slotlar yeniden planlanmalı. Var olan
    # planned slotlar eski ayara göre yazılmış — ezmek yerine SİLİP yeniden yazdırıyoruz
    # (üretilmiş/yüklenmiş slotlara DOKUNULMAZ).
    from short_bot.db import delete_planned_slots
    silinen = delete_planned_slots(init_db(current_app.config["SHORTBOT_DB_PATH"]),
                                   slug)
    # ve HEMEN yeniden planla — kullanıcı sonucu ANINDA görmeli.
    yazilan = _plan_now(slug)
    flash(f"Ayarlar kaydedildi. {silinen} planlı slot silindi, "
          f"{yazilan} yeni slot yazıldı.", "success")
    return redirect(url_for("autopilot.page", slug=slug))


@bp.post("/channels/<slug>/autopilot/enable")
def enable(slug):
    """Otomasyonu aç ve slotları HEMEN planla."""
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None) or AutopilotConfig()
    _save(cfg, slug, ap.model_copy(update={"enabled": True}))
    n = _plan_now(slug)
    flash(f"Otomasyon açıldı — {n} slot planlandı. Kanalın normal cron'u artık "
          f"koşmayacak (çifte üretim olmasın diye).", "success")
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
    # Kanal kapalıyken planlama HİÇ koşmuyordu (plan_channel devre dışı kanalı atlar).
    # Açılır açılmaz planla — yoksa kullanıcı sabah 03:30'a kadar boş sayfa görürdü.
    n = _plan_now(slug)
    flash(f"Kanal etkinleştirildi — {n} slot planlandı. Otomasyon çalışmaya başladı.",
          "success")
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
