"""Panelde görünen tarihler — Türkçe.

Şablonlar tarihi ``strftime('%d %b %H:%M')`` ile yazıyordu. ``%b``/``%B``/``%A``
işletim sisteminin C yerelini kullanır ve bu kurulumda İngilizce döner: baştan
sona Türkçe bir arayüzde «22 Aug 18:11» ve «23 August Sunday» yazıyordu
(ölçüldü: shorts ızgarası, short detayı, kanal koşu tablosu, YouTube istatistik
satırı, cron zaman çizelgesi — beş yer).

``locale.setlocale`` ÇÖZÜM DEĞİL: süreç genelinde durum değiştirir, Windows'ta
ad ("Turkish_Turkey.1254") platforma göre değişir ve kurulu değilse patlar.
Ayrıca bu panel her zaman Türkçe — çevrilecek bir şey yok, sabit tablo yeter.
"""
from __future__ import annotations

from datetime import date, datetime

AYLAR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
         "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")

#: Kısa biçim — dar sütunlarda ay adı satırı taşırıyordu.
AYLAR_KISA = ("Oca", "Şub", "Mar", "Nis", "May", "Haz",
              "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")

GUNLER = ("Pazartesi", "Salı", "Çarşamba", "Perşembe",
          "Cuma", "Cumartesi", "Pazar")


def ay_adi(ay: int, *, kisa: bool = False) -> str:
    tablo = AYLAR_KISA if kisa else AYLAR
    return tablo[ay - 1]


def gun_adi(d: date | datetime) -> str:
    return GUNLER[d.weekday()]


def tr_tarih(d: date | datetime | None, bicim: str = "gun_ay_saat") -> str:
    """Türkçe tarih. Tanınmayan biçim adı çağıranı düşürmez, ISO'ya döner.

    Biçimler:
      ``gun_ay``        → 22 Ağu
      ``gun_ay_saat``   → 22 Ağu 18:11
      ``gun_ay_yil``    → 22 Ağustos 2026
      ``tam``           → 22 Ağustos 2026, 18:11
      ``gun_ay_gunadi`` → 23 Ağustos Pazar
      ``saat``          → 18:11
    """
    if d is None:
        return "—"
    saat = f"{d.hour:02d}:{d.minute:02d}" if isinstance(d, datetime) else ""
    if bicim == "gun_ay":
        return f"{d.day} {ay_adi(d.month, kisa=True)}"
    if bicim == "gun_ay_saat":
        return f"{d.day} {ay_adi(d.month, kisa=True)} {saat}".strip()
    if bicim == "gun_ay_yil":
        return f"{d.day} {ay_adi(d.month)} {d.year}"
    if bicim == "tam":
        temel = f"{d.day} {ay_adi(d.month)} {d.year}"
        return f"{temel}, {saat}" if saat else temel
    if bicim == "gun_ay_gunadi":
        return f"{d.day} {ay_adi(d.month)} {gun_adi(d)}"
    if bicim == "saat":
        return saat or f"{d.day} {ay_adi(d.month, kisa=True)}"
    return d.isoformat()
