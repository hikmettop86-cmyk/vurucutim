"""Autopilot zamanlaması — SAF. DB yok, saat yok, ağ yok, LLM yok.

NEDEN SAF: yanlış bir slot saati HATA VERMEZ. Video yanlış saatte yayınlanır ya da
hiç yayınlanmaz — ve bunu ancak günler sonra fark edersin. Bütün zamanlama mantığını
yan etkisiz bir modülde toplamak, onu yüzlerce senaryoyla saniyeler içinde
sınayabilmenin tek yolu.

İNSAN RİTMİ = RASTGELE YÜRÜYÜŞ, DÜZ RASTGELELİK DEĞİL.
Her gün 10:00-22:00 arasında rastgele bir an seçmek ritmi TAMAMEN yok eder; izleyici
alışkanlık kuramaz, kanal "ne zaman paylaşacağı belli olmayan" bir yere döner. İnsan
ise bir taban etrafında SÜRÜKLENİR:
    13:00 → 13:10 → 13:04 → 13:00
Bunu bir taban + sınırlı adımlı, sınırlı genlikli bir rastgele yürüyüşle modelliyoruz.

Yürüyüş DETERMİNİSTİK (sha1): aynı gün iki kez planlanırsa slot KAYMAZ. Uygulama
yeniden başladığında planlayıcı yeniden koşuyor — kayan bir slot, üretilmiş bir videoyu
yanlış saate zamanlardı.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, time, timedelta, timezone

# İki slot bu kadar yakınsa "insan" değil: aynı yarım saatte iki video paylaşan bir
# hesap, otomasyon olduğunu ilan eder.
MIN_SLOT_GAP_MIN = 30
# live_upload modunda uygulama slot anında kapalıysa bu kadar gecikmeye izin ver.
# Fazlası GEÇ YÜKLEME olur — ritmi bozar, hedeflenen saati ıskalar.
LIVE_GRACE_MIN = 15


@dataclass(frozen=True, order=True)
class Slot:
    slot_index: int
    slot_at_utc: datetime
    jitter_min: int          # HAM sapma — ertesi günün yürüyüşü buradan devam eder


def base_minutes(active_hours: tuple[int, int], daily_count: int) -> list[int]:
    """Taban saatler (yerel gün içinde dakika). Aktif saatler N eşit bloğa bölünür ve
    slot her bloğun ORTASINA oturur.

    ORTAYA oturtmak keyfi değil: uçlara koyarsak (10:00 ve 22:00) jitter aktif
    saatlerden TAŞAR ve kırpılmak zorunda kalır — kırpma da jitter'ı bir uca yapıştırır
    ve "insan ritmi" ölür. Blok ortası, jitter'a her iki yönde yer bırakır.
    """
    lo, hi = active_hours
    n = max(1, int(daily_count))
    blok = (hi - lo) * 60 / n
    return [int(lo * 60 + blok * (i + 0.5)) for i in range(n)]


def _step(channel: str, slot_index: int, date_str: str, step_max: int) -> int:
    """Bugünkü adım — DETERMİNİSTİK. Aynı (kanal, slot, gün) → aynı adım."""
    h = int(hashlib.sha1(
        f"{channel}:{slot_index}:{date_str}".encode("utf-8")).hexdigest(), 16)
    return (h % (2 * step_max + 1)) - step_max


def next_jitter(prev: int, *, channel: str, slot_index: int, date_str: str,
                step_max: int, jitter_max: int) -> int:
    """Rastgele yürüyüş: dünkü sapma ± adım, genlik tavanına sıkıştırılır."""
    j = int(prev) + _step(channel, slot_index, date_str, step_max)
    return max(-jitter_max, min(jitter_max, j))


def plan_day(channel: str, date_local: _date, *, cfg, prev_jitters: dict[int, int],
             tz) -> list[Slot]:
    """O günün slotları.

    ``prev_jitters``: {slot_index: dünkü HAM sapma}. Yoksa 0'dan başlar.

    İKİ KORUMA (aksi hâlde sessizce bozulur):
      1. Slot aktif saatlerin DIŞINA çıkamaz.
      2. İki slot arası en az MIN_SLOT_GAP_MIN kalır.

    Ama KAYDEDİLEN jitter HAM değerdir. Kırpılmış değeri kaydedersek yürüyüş yanlı
    hâle gelir: her gün sınıra çarpan bir yürüyüş oraya yapışır ve slot saati sabitlenir
    — yani tam da kaçınmaya çalıştığımız şey olur.
    """
    lo, hi = cfg.active_hours
    bases = base_minutes((lo, hi), cfg.daily_count)
    out: list[Slot] = []
    onceki_dk: int | None = None
    for i, taban in enumerate(bases):
        ham = next_jitter(int(prev_jitters.get(i, 0)), channel=channel, slot_index=i,
                          date_str=date_local.isoformat(),
                          step_max=cfg.jitter_step, jitter_max=cfg.jitter_minutes)
        dk = taban + ham
        dk = max(lo * 60, min(hi * 60 - 1, dk))                  # aktif saatler
        if onceki_dk is not None and dk - onceki_dk < MIN_SLOT_GAP_MIN:
            dk = min(hi * 60 - 1, onceki_dk + MIN_SLOT_GAP_MIN)  # çakışma
        onceki_dk = dk
        yerel = datetime.combine(date_local, time(0, 0), tzinfo=tz) \
            + timedelta(minutes=dk)
        out.append(Slot(slot_index=i,
                        slot_at_utc=yerel.astimezone(timezone.utc),
                        jitter_min=ham))
    return out


def produce_at(slot_at_utc: datetime, lead_hours: int) -> datetime:
    """Üretimin BAŞLAMASI gereken an."""
    return slot_at_utc - timedelta(hours=int(lead_hours))


def slot_is_due(slot_at_utc: datetime, now_utc: datetime, lead_hours: int) -> bool:
    return produce_at(slot_at_utc, lead_hours) <= now_utc


def is_stale(slot_at_utc: datetime, now_utc: datetime) -> bool:
    """Slot anı geçti ve hâlâ üretilmedi → kaçtı. GEÇ YÜKLEME YOK: 22:00'de yayınlanan
    bir 'gündüz videosu' hedefini zaten ıskalar ve ritmi bozar."""
    return now_utc > slot_at_utc
