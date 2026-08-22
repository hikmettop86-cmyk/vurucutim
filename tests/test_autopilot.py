"""Autopilot zamanlaması: insan ritmi, çakışmasız, deterministik.

SESSİZ BOZULMA RİSKİ: yanlış bir slot saati HATA VERMEZ — sadece video yanlış saatte
(ya da hiç) yayınlanır, ve bunu ancak günler sonra fark edersin. O yüzden bu modülün
her kuralı ölçülüyor.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from short_bot.autopilot import (LIVE_GRACE_MIN, MIN_SLOT_GAP_MIN, base_minutes,
                                 is_stale, next_jitter, plan_day, produce_at,
                                 slot_is_due)

TR = ZoneInfo("Europe/Istanbul")


class _Cfg:
    daily_count = 3
    active_hours = (10, 22)
    jitter_minutes = 15
    jitter_step = 6
    produce_lead_hours = 3


def _gunler(n=28):
    return [date(2026, 7, 1) + __import__("datetime").timedelta(days=i)
            for i in range(n)]


# --- TABAN SAATLER ---------------------------------------------------------

def test_taban_saatler_blok_ORTALARINA_oturur():
    """Uçlara koyarsak jitter aktif saatlerden TAŞAR. Ortaya koyunca taşma yapısal
    olarak imkânsız — ve kırpma jitter'ı bir uca yapıştırmaz."""
    assert base_minutes((10, 22), 3) == [12 * 60, 16 * 60, 20 * 60]


def test_taban_saatler_sirali_ve_aktif_saatler_icinde():
    for n in (1, 2, 3, 5, 8):
        b = base_minutes((9, 23), n)
        assert len(b) == n
        assert b == sorted(b)
        assert all(9 * 60 <= x < 23 * 60 for x in b)


def test_tek_slot_ORTAYA_oturur():
    assert base_minutes((10, 22), 1) == [16 * 60]


# --- JITTER: RASTGELE YÜRÜYÜŞ ----------------------------------------------

def test_jitter_deterministik():
    a = next_jitter(0, channel="k", slot_index=0, date_str="2026-07-14",
                    step_max=6, jitter_max=15)
    b = next_jitter(0, channel="k", slot_index=0, date_str="2026-07-14",
                    step_max=6, jitter_max=15)
    assert a == b


def test_jitter_ADIM_sinirini_asmaz():
    """Bir günde 40 dakika kayan bir hesap 'insan' değildir."""
    j = 0
    for g in _gunler(60):
        yeni = next_jitter(j, channel="k", slot_index=0, date_str=g.isoformat(),
                           step_max=6, jitter_max=15)
        assert abs(yeni - j) <= 6, f"adım {yeni - j} > 6"
        j = yeni


def test_jitter_TAVANI_asmaz():
    j = 0
    for g in _gunler(60):
        j = next_jitter(j, channel="k", slot_index=0, date_str=g.isoformat(),
                        step_max=6, jitter_max=15)
        assert -15 <= j <= 15


def test_jitter_GERCEKTEN_degisir():
    """Sabit kalan bir jitter = her gün aynı dakika = otomasyon parmak izi."""
    j, gorulen = 0, set()
    for g in _gunler(28):
        j = next_jitter(j, channel="k", slot_index=0, date_str=g.isoformat(),
                        step_max=6, jitter_max=15)
        gorulen.add(j)
    assert len(gorulen) >= 5, f"jitter yeterince gezinmiyor: {sorted(gorulen)}"


def test_farkli_kanal_farkli_yuruyus():
    j = {c: next_jitter(0, channel=c, slot_index=0, date_str="2026-07-14",
                        step_max=6, jitter_max=15) for c in "abcdef"}
    assert len(set(j.values())) > 1


def test_farkli_slot_farkli_yuruyus():
    j = {i: next_jitter(0, channel="k", slot_index=i, date_str="2026-07-14",
                        step_max=6, jitter_max=15) for i in range(6)}
    assert len(set(j.values())) > 1


# --- GÜN PLANI -------------------------------------------------------------

def test_plan_deterministik():
    a = plan_day("k", date(2026, 7, 14), cfg=_Cfg(), prev_jitters={}, tz=TR)
    b = plan_day("k", date(2026, 7, 14), cfg=_Cfg(), prev_jitters={}, tz=TR)
    assert a == b, "uygulama yeniden başlayınca slot KAYMAMALI"


def test_slotlar_AKTIF_SAATLER_icinde():
    class _Wide(_Cfg):
        daily_count = 8
        jitter_minutes = 90       # kasten aşırı

    for g in _gunler(14):
        for s in plan_day("k", g, cfg=_Wide(), prev_jitters={}, tz=TR):
            yerel = s.slot_at_utc.astimezone(TR)
            assert 10 <= yerel.hour < 22, f"{yerel} aktif saatler dışında"


def test_slotlar_CAKISMAZ():
    class _Tight(_Cfg):
        daily_count = 8
        jitter_minutes = 60

    s = plan_day("k", date(2026, 7, 14), cfg=_Tight(), prev_jitters={}, tz=TR)
    for a, b in zip(s, s[1:]):
        fark = (b.slot_at_utc - a.slot_at_utc).total_seconds() / 60
        assert fark >= MIN_SLOT_GAP_MIN, f"slotlar {fark:.0f}dk arayla — çakışıyor"


def test_slotlar_SIRALI():
    s = plan_day("k", date(2026, 7, 14), cfg=_Cfg(), prev_jitters={}, tz=TR)
    assert [x.slot_index for x in s] == [0, 1, 2]
    assert s == sorted(s, key=lambda x: x.slot_at_utc)


def test_jitter_ONCEKI_GUNDEN_yuruyor():
    """Kullanıcının tarifi: 13:00 → 13:10 → 13:04 → 13:00. Düz rastgelelik DEĞİL."""
    gun1 = plan_day("k", date(2026, 7, 14), cfg=_Cfg(), prev_jitters={}, tz=TR)
    onceki = {s.slot_index: s.jitter_min for s in gun1}
    gun2 = plan_day("k", date(2026, 7, 15), cfg=_Cfg(), prev_jitters=onceki, tz=TR)
    for a, b in zip(gun1, gun2):
        assert abs(b.jitter_min - a.jitter_min) <= _Cfg.jitter_step


def test_yuruyus_gunler_boyunca_TABAN_etrafinda_gezinir():
    """Uçtan uca: 14 gün boyunca slot saati taban ± jitter_minutes içinde kalmalı,
    ama SABİT de kalmamalı."""
    onceki, saatler = {}, []
    for g in _gunler(14):
        gun = plan_day("k", g, cfg=_Cfg(), prev_jitters=onceki, tz=TR)
        onceki = {s.slot_index: s.jitter_min for s in gun}
        yerel = gun[0].slot_at_utc.astimezone(TR)
        saatler.append(yerel.hour * 60 + yerel.minute)
    taban = 12 * 60
    assert all(abs(m - taban) <= _Cfg.jitter_minutes for m in saatler), saatler
    assert len(set(saatler)) >= 5, f"saat gezinmiyor: {saatler}"


def test_kaydedilen_jitter_HAM_deger():
    """Kırpılmış (aktif saat / çakışma) değer kaydedilirse yürüyüş YANLI olur ve
    jitter zamanla bir uca yapışır — ritim yine ölür."""
    class _Wide(_Cfg):
        daily_count = 8
        jitter_minutes = 90

    for s in plan_day("k", date(2026, 7, 14), cfg=_Wide(), prev_jitters={}, tz=TR):
        assert -90 <= s.jitter_min <= 90


def test_dst_gecisinde_cokmez():
    """TR'de DST yok ama kod başka saat dilimlerinde de koşabilmeli."""
    berlin = ZoneInfo("Europe/Berlin")
    s = plan_day("k", date(2026, 3, 29), cfg=_Cfg(), prev_jitters={}, tz=berlin)
    assert len(s) == 3
    assert all(x.slot_at_utc.tzinfo is timezone.utc for x in s)


# --- ÜRETİM / DURUM KARARLARI ----------------------------------------------

def test_produce_at_lead_kadar_once():
    slot = datetime(2026, 7, 14, 13, 4, tzinfo=timezone.utc)
    assert produce_at(slot, 3) == datetime(2026, 7, 14, 10, 4, tzinfo=timezone.utc)


def test_slot_due_ancak_lead_gelince():
    slot = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    assert not slot_is_due(slot, datetime(2026, 7, 14, 9, 59, tzinfo=timezone.utc), 3)
    assert slot_is_due(slot, datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc), 3)
    assert slot_is_due(slot, datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc), 3)


def test_slot_gecmisse_STALE():
    """Uygulama kapalıydı → slot kaçtı. GEÇ YÜKLEME YOK."""
    slot = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    assert not is_stale(slot, datetime(2026, 7, 14, 12, 59, tzinfo=timezone.utc))
    assert is_stale(slot, datetime(2026, 7, 14, 13, 1, tzinfo=timezone.utc))


def test_sabitler_makul():
    assert 15 <= MIN_SLOT_GAP_MIN <= 60
    assert 5 <= LIVE_GRACE_MIN <= 30
