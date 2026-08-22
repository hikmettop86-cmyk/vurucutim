"""GÜNDE EN FAZLA 1 SERİ BÖLÜMÜ.

SESSİZ BOZULMA: seri bölümü izleyiciye "#2 YARIN" diye söz veriyor (abone çipi).
Günde 3 bölüm üretilirse 3 bölümlük ark BİR GÜNDE biter ve #2 aynı gün yayınlanır —
söz YALAN olur, abone takası çöker ve Faz 3'ün bütün mekanizması anlamsızlaşır.

Kalan slotlar bankadan BAĞIMSIZ konu üretir: seriyi ilerletmez, ark tüketmez.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from short_bot.autopilot import KIND_SERIES, KIND_STANDALONE, plan_day
from short_bot.autopilot_runner import AutopilotDeps, plan_channel, tick
from short_bot.db import (init_db, record_short, slots_for_date)

UTC = timezone.utc
TR = ZoneInfo("Europe/Istanbul")


class _AP:
    enabled = True
    daily_count = 3
    active_hours = (10, 22)
    timezone = "Europe/Istanbul"
    jitter_minutes = 15
    jitter_step = 6
    produce_lead_hours = 3
    publish_mode = "publish_at"
    max_attempts = 3
    series_per_day = 1


class _Reel:
    enabled = True
    series_enabled = True


class _YT:
    auto_upload = True


class _Ch:
    slug = "k"
    enabled = True
    autopilot = _AP()
    reel = _Reel()
    youtube = _YT()


# --- SAF: plan_day türü işaretliyor mu? ------------------------------------

def test_ILK_slot_seri_KALANLAR_bagimsiz():
    s = plan_day("k", date(2026, 7, 14), cfg=_AP(), prev_jitters={}, tz=TR,
                 series_slots=1)
    assert [x.kind for x in s] == [KIND_SERIES, KIND_STANDALONE, KIND_STANDALONE]


def test_seri_HER_GUN_AYNI_slotta():
    """İzleyici 'yeni bölüm öğlen gelir' diye alışkanlık kurabilmeli. Rastgele bir
    slota koymak, serinin tek gerçek avantajını — beklenebilirliği — harcar."""
    for g in (date(2026, 7, 14), date(2026, 7, 15), date(2026, 7, 16)):
        s = plan_day("k", g, cfg=_AP(), prev_jitters={}, tz=TR, series_slots=1)
        seri = [x for x in s if x.kind == KIND_SERIES]
        assert len(seri) == 1
        assert seri[0].slot_index == 0


def test_series_slots_0_ise_HIC_seri_yok():
    s = plan_day("k", date(2026, 7, 14), cfg=_AP(), prev_jitters={}, tz=TR,
                 series_slots=0)
    assert all(x.kind == KIND_STANDALONE for x in s)


def test_series_slots_2_ise_ILK_IKI_seri():
    s = plan_day("k", date(2026, 7, 14), cfg=_AP(), prev_jitters={}, tz=TR,
                 series_slots=2)
    assert [x.kind for x in s] == [KIND_SERIES, KIND_SERIES, KIND_STANDALONE]


# --- PLANLAMA: DB'ye tür yazılıyor mu? ------------------------------------

def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def test_plan_channel_turu_DBye_yazar(tmp_path):
    eng = _eng(tmp_path)
    plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=1)
    s = slots_for_date(eng, "k", "2026-07-14")
    assert [x["kind"] for x in s] == ["series", "standalone", "standalone"]


def test_SERI_KAPALIYSA_hicbiri_seri_degil(tmp_path):
    class _Off(_Ch):
        class reel(_Reel):
            series_enabled = False

    eng = _eng(tmp_path)
    plan_channel(eng, _Off(), today_local=date(2026, 7, 14), days=1)
    s = slots_for_date(eng, "k", "2026-07-14")
    assert all(x["kind"] == "standalone" for x in s)


def test_series_per_day_daily_counttan_BUYUK_olamaz(tmp_path):
    """Ayar hatalı olsa bile plan bozulmamalı."""
    class _Fazla(_Ch):
        class autopilot(_AP):
            daily_count = 2
            series_per_day = 5

    eng = _eng(tmp_path)
    plan_channel(eng, _Fazla(), today_local=date(2026, 7, 14), days=1)
    s = slots_for_date(eng, "k", "2026-07-14")
    assert len(s) == 2
    assert all(x["kind"] == "series" for x in s)   # 2 slot, ikisi de seri (cap)


# --- ÜRETİM: bağımsız slot seriyi İLERLETMEZ ------------------------------

class _Res:
    def __init__(self, short_id):
        self.status = "success"
        self.short_id = short_id
        self.run_id = None
        self.error = None


def _deps(now, cagri):
    def _p(cfg, series):
        cagri["produce"].append(series)
        return _Res(cagri["short_id"])

    def _a(cfg):
        cagri["arc"].append(cfg.slug)

    return AutopilotDeps(produce=_p,
                         upload_scheduled=lambda *a: "u",
                         upload_live=lambda *a: "u",
                         ensure_arc=_a, now=lambda: now)


def test_SERI_slotunda_seri_URETILIR(tmp_path):
    eng = _eng(tmp_path)
    plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=1)
    sid = record_short(eng, channel="k", rss_item_guid=None, title="T",
                       file_path="v.mp4", duration_s=40, script_json="{}",
                       render_ms=1)
    ilk = slots_for_date(eng, "k", "2026-07-14")[0]
    now = ilk["slot_at_utc"].replace(tzinfo=UTC)

    cagri = {"produce": [], "arc": [], "short_id": sid}
    tick(eng, _Ch(), _deps(now.replace(hour=now.hour - 1), cagri))
    assert cagri["produce"] == [True], "seri slotunda bağımsız üretim yapıldı"
    assert cagri["arc"] == ["k"], "seri slotunda ark sağlanmadı"


def test_BAGIMSIZ_slotta_ARK_SAGLANMAZ(tmp_path):
    """Bağımsız video seriyi ilerletmeyecek — ark için LLM yakmanın anlamı yok."""
    eng = _eng(tmp_path)
    plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=1)
    sid = record_short(eng, channel="k", rss_item_guid=None, title="T",
                       file_path="v.mp4", duration_s=40, script_json="{}",
                       render_ms=1)
    s = slots_for_date(eng, "k", "2026-07-14")
    # İlk (seri) slotu SONUÇLANDIR ki sıradaki bağımsız slot işlensin
    from short_bot.db import slot_set_status
    slot_set_status(eng, s[0]["id"], "published", short_id=sid)

    ikinci = s[1]["slot_at_utc"].replace(tzinfo=UTC)
    cagri = {"produce": [], "arc": [], "short_id": sid}
    tick(eng, _Ch(), _deps(ikinci.replace(hour=ikinci.hour - 1), cagri))

    assert cagri["produce"] == [False], "bağımsız slotta SERİ bölümü üretildi"
    assert cagri["arc"] == [], "bağımsız slotta boşuna ark planlandı (LLM yakıldı)"


def test_bir_GUNDE_yalniz_BIR_seri_bolumu(tmp_path):
    """Mekanizmanın özü: 3 videoluk bir günde 1 seri bölümü, 2 bağımsız."""
    eng = _eng(tmp_path)
    plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=1)
    turler = [x["kind"] for x in slots_for_date(eng, "k", "2026-07-14")]
    assert turler.count("series") == 1
    assert turler.count("standalone") == 2
