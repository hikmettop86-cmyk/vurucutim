"""Autopilot durum makinesi.

YAN ETKİLER ENJEKTE EDİLİR (AutopilotDeps): üretim, yükleme, ark planlama ve SAAT
dışarıdan gelir. Böylece bütün durum geçişleri APScheduler'sız, ağsız, LLM'siz test
edilir — zamanlama hatası üretime sızmadan yakalanır.

SESSİZ BOZULMA ALANLARI (hepsinin testi var):
  • Slot anı geçmişken publishAt vermek → YouTube REDDETMEZ, videoyu ANINDA yayınlar.
  • Yükleme patlayınca slot'u 'scheduled' işaretlemek → video hiç yüklenmemiş olur ama
    panel "yayına zamanlandı" der.
  • max_attempts'i saymamak → sonsuza kadar üretim denemesi; ai33/LLM kredisini yakar.
  • Aynı tick'te iki üretim başlatmak → pipeline kanal başına KİLİTLİ; ikincisi
    'lock busy' ile düşer ve slot boşuna bir deneme harcar.
  • Ark bitmişken üretmek → bölüm bankadan TEK KONU olarak çıkar, seri delinir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from short_bot.autopilot import LIVE_GRACE_MIN, is_stale, plan_day, slot_is_due
from short_bot.db import (open_slots, plan_slots, prev_day_jitters,
                          slot_bump_attempt, slot_set_status)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutopilotDeps:
    produce: Callable           # (cfg) -> RunResult
    upload_scheduled: Callable  # (short_id, cfg, publish_at: str) -> url
    upload_live: Callable       # (short_id, cfg) -> url
    ensure_arc: Callable        # (cfg) -> None  (ark bitmişse yenisini planla+onayla)
    now: Callable               # () -> datetime (UTC)


def _rfc3339(dt: datetime) -> str:
    """YouTube publishAt biçimi: RFC3339, Z sonekiyle UTC."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_utc(dt: datetime) -> datetime:
    """SQLite naive datetime döndürüyor — UTC varsay (yazarken UTC yazıyoruz).

    Bu dönüşüm olmadan aware/naive karşılaştırması TypeError verir; daha kötüsü,
    yanlış varsayımla saatler kayardı.
    """
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def plan_channel(eng, cfg, *, today_local: _date, days: int = 2) -> int:
    """Bugünden itibaren ``days`` günün slotlarını yaz. İDEMPOTENT.

    Uygulama AÇILIŞINDA da koşar: uygulama kapalıysa gece cron'u kaçar ve o gün
    tamamen boş geçerdi.
    """
    ap = getattr(cfg, "autopilot", None)
    if ap is None or not ap.enabled or not getattr(cfg, "enabled", True):
        return 0
    tz = ZoneInfo(ap.timezone)
    toplam = 0
    for k in range(max(1, days)):
        gun = today_local + timedelta(days=k)
        slots = plan_day(cfg.slug, gun, cfg=ap,
                         prev_jitters=prev_day_jitters(eng, cfg.slug, gun), tz=tz)
        toplam += plan_slots(eng, cfg.slug, gun.isoformat(), [
            {"slot_index": s.slot_index, "slot_at_utc": s.slot_at_utc,
             "jitter_min": s.jitter_min} for s in slots])
    return toplam


def _kacanlari_isaretle(eng, cfg, slots, now, sayac) -> None:
    """Slot anı geçmiş ama hâlâ üretilmemiş → KAÇTI.

    GEÇ YÜKLEME YOK: 22:00'de yayınlanan bir 'gündüz videosu' hedefini zaten ıskalar
    ve ritmi bozar. Video kaybetmek, ritim kaybetmekten iyidir.
    """
    for s in slots:
        if s["status"] in ("planned", "producing") and \
                is_stale(_as_utc(s["slot_at_utc"]), now):
            slot_set_status(eng, s["id"], "skipped",
                            error="slot anı geçti (uygulama kapalıydı)")
            sayac["skipped"] += 1
            log.info(f"[autopilot] {cfg.slug} slot {s['slot_index']} KAÇTI")


def tick(eng, cfg, deps: AutopilotDeps) -> dict:
    """Bir tur: kaçanları işaretle → yükle → üret. Sayaç döndürür."""
    ap = getattr(cfg, "autopilot", None)
    if ap is None or not ap.enabled:
        return {}
    now = deps.now()
    sayac = {"skipped": 0, "produced": 0, "failed": 0,
             "scheduled": 0, "published": 0}

    # 1) KAÇANLAR
    _kacanlari_isaretle(eng, cfg, open_slots(eng, cfg.slug), now, sayac)

    # 2) YÜKLEME — ÜRETİMDEN ÖNCE. Üretim ~15 dk sürüyor; bekleyen bir yükleme onun
    #    arkasına düşerse slot anını kaçırabilir.
    _yukle(eng, cfg, ap, now, sayac, deps)

    # 3) ZAMANLANMIŞ + slot anı geçti → YouTube yayınladı.
    for s in open_slots(eng, cfg.slug):
        if s["status"] == "scheduled" and now >= _as_utc(s["slot_at_utc"]):
            slot_set_status(eng, s["id"], "published")
            sayac["published"] += 1

    # 4) ÜRETİM — TEK slot. Pipeline kanal başına KİLİTLİ ve üretim ~15 dk sürüyor;
    #    ikinci üretimi aynı tick'te başlatmak onu 'lock busy' → failed yapar ve slot
    #    boşuna bir deneme harcar.
    due = [s for s in open_slots(eng, cfg.slug)
           if s["status"] == "planned"
           and slot_is_due(_as_utc(s["slot_at_utc"]), now, ap.produce_lead_hours)]
    if not due:
        return sayac
    s = due[0]

    # ARK — ÜRETİMDEN ÖNCE. Ark bitmişse yeni ark planlanıp oto-onaylanmalı; yoksa bu
    # bölüm bankadan TEK KONU olarak çıkar ve seri delinir.
    try:
        deps.ensure_arc(cfg)
    except Exception as e:   # noqa: BLE001 — ark üretimi DURDURMAMALI
        log.warning(f"[autopilot] {cfg.slug} ark sağlanamadı ({e})")

    slot_set_status(eng, s["id"], "producing")
    n = slot_bump_attempt(eng, s["id"])
    log.info(f"[autopilot] {cfg.slug} slot {s['slot_index']} üretiliyor "
             f"(deneme {n}/{ap.max_attempts})")

    res, hata = None, "üretim başarısız"
    try:
        res = deps.produce(cfg)
    except Exception as e:   # noqa: BLE001
        hata = str(e)
    else:
        hata = getattr(res, "error", None) or hata

    if res is not None and getattr(res, "status", "") == "success" \
            and getattr(res, "short_id", None):
        slot_set_status(eng, s["id"], "produced", short_id=res.short_id,
                        run_id=getattr(res, "run_id", None))
        sayac["produced"] += 1
        # publish_at modunda beklemenin anlamı yok: hemen zamanla.
        if ap.publish_mode == "publish_at":
            _yukle(eng, cfg, ap, deps.now(), sayac, deps)
        return sayac

    if n >= ap.max_attempts:
        slot_set_status(eng, s["id"], "failed", error=hata)
        sayac["failed"] += 1
        log.warning(f"[autopilot] {cfg.slug} slot {s['slot_index']} {n} denemede "
                    f"üretilemedi → slot BOŞ geçecek ({hata})")
    else:
        slot_set_status(eng, s["id"], "planned", error=hata)
    return sayac


# --- yükleme ---------------------------------------------------------------
# Ayrı fonksiyon: tick hem BAŞTA (bekleyen yüklemeler) hem BAŞARILI ÜRETİMDEN SONRA
# çağırıyor. publish_at modunda üretim biter bitmez zamanlamanın anlamı var —
# bir sonraki tick'i (5 dk) beklemek slot anını kaçırma riskini büyütür.

def _yukle(eng, cfg, ap, now, sayac, deps: AutopilotDeps) -> None:
    for s in open_slots(eng, cfg.slug):
        if s["status"] != "produced" or not s["short_id"]:
            continue
        slot_at = _as_utc(s["slot_at_utc"])

        if ap.publish_mode == "publish_at":
            if now >= slot_at:
                # publishAt GEÇMİŞE zamanlanamaz. YouTube REDDETMEZ — videoyu ANINDA
                # yayınlar ve ritim çöker. Slotu düşür.
                slot_set_status(eng, s["id"], "failed",
                                error="slot anı geçti, publishAt geçersiz")
                sayac["failed"] += 1
                continue
            try:
                url = deps.upload_scheduled(s["short_id"], cfg, _rfc3339(slot_at))
                slot_set_status(eng, s["id"], "scheduled")
                sayac["scheduled"] += 1
                log.info(f"[autopilot] {cfg.slug} slot {s['slot_index']} → "
                         f"{_rfc3339(slot_at)} zamanlandı ({url})")
            except Exception as e:   # noqa: BLE001 — 'produced'ta KALIR, tekrar denenir
                log.warning(f"[autopilot] {cfg.slug} zamanlı yükleme hatası: {e}")
            continue

        # live_upload
        if now < slot_at:
            continue
        if now > slot_at + timedelta(minutes=LIVE_GRACE_MIN):
            slot_set_status(
                eng, s["id"], "failed",
                error=f"slot anı {LIVE_GRACE_MIN} dakikadan fazla geçti "
                      f"(geç yükleme yok)")
            sayac["failed"] += 1
            continue
        try:
            url = deps.upload_live(s["short_id"], cfg)
            slot_set_status(eng, s["id"], "published")
            sayac["published"] += 1
            log.info(f"[autopilot] {cfg.slug} slot {s['slot_index']} "
                     f"canlı yüklendi ({url})")
        except Exception as e:   # noqa: BLE001
            log.warning(f"[autopilot] {cfg.slug} canlı yükleme hatası: {e}")
