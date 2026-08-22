"""Autopilot durum makinesi — bütün sessiz bozulma senaryoları.

Yan etkiler AutopilotDeps ile enjekte edilir: APScheduler yok, ağ yok, LLM yok.
Testler saniyeler içinde koşar ve HER geçişi ölçer.
"""
from datetime import date, datetime, timezone

import pytest

from short_bot.autopilot import LIVE_GRACE_MIN
from short_bot.autopilot_runner import AutopilotDeps, plan_channel, tick
from short_bot.db import (init_db, plan_slots, record_short, slot_set_status,
                          slots_for_date, start_run)

UTC = timezone.utc


class _AP:
    enabled = True
    daily_count = 2
    active_hours = (10, 22)
    timezone = "Europe/Istanbul"
    jitter_minutes = 15
    jitter_step = 6
    produce_lead_hours = 3
    publish_mode = "publish_at"
    max_attempts = 3


class _YT:
    auto_upload = True          # kullanıcı otomatik yüklemeye İZİN verdi


class _Ch:
    slug = "k"
    enabled = True
    autopilot = _AP()
    youtube = _YT()


class _Live(_Ch):
    class autopilot(_AP):
        publish_mode = "live_upload"


class _Res:
    def __init__(self, status="success", short_id=1, run_id=None, error=None):
        self.status = status
        self.short_id = short_id
        self.run_id = run_id
        self.error = error


def _deps(now, *, produce=None, sched=None, live=None, arc=None):
    cagri = {"produce": [], "sched": [], "live": [], "arc": []}

    def _p(cfg, series=True):
        cagri["produce"].append(cfg.slug)
        cagri.setdefault("series", []).append(series)
        return (produce or (lambda: _Res()))()

    def _s(short_id, cfg, publish_at):
        cagri["sched"].append((short_id, publish_at))
        return (sched or (lambda: "https://youtu.be/X"))()

    def _l(short_id, cfg):
        cagri["live"].append(short_id)
        return (live or (lambda: "https://youtu.be/Y"))()

    def _a(cfg):
        cagri["arc"].append(cfg.slug)
        return (arc or (lambda: None))()

    return AutopilotDeps(produce=_p, upload_scheduled=_s, upload_live=_l,
                         ensure_arc=_a, now=lambda: now), cagri


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _slot(eng, hour, minute=0, index=0, kind="series"):
    """Bu dosyadaki testler GENEL üretim akışını ölçüyor → varsayılan SERİ slotu.
    Slot türünün kendi testleri test_autopilot_series_per_day.py'de."""
    plan_slots(eng, "k", "2026-07-14", [
        {"slot_index": index,
         "slot_at_utc": datetime(2026, 7, 14, hour, minute, tzinfo=UTC),
         "jitter_min": 0, "kind": kind}])
    return slots_for_date(eng, "k", "2026-07-14")[index]


def _gercek_short(eng) -> int:
    """slot.short_id bir FOREIGN KEY — uydurma id kabul edilmez."""
    return record_short(eng, channel="k", rss_item_guid=None, title="Baslik",
                        file_path="out/v.mp4", duration_s=40, script_json="{}",
                        render_ms=1)


def _durum(eng, index=0):
    return slots_for_date(eng, "k", "2026-07-14")[index]


# --- PLANLAMA --------------------------------------------------------------

def test_plan_bugun_ve_yarini_yazar(tmp_path):
    eng = _eng(tmp_path)
    n = plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=2)
    assert n == 4                                    # 2 slot × 2 gün
    assert len(slots_for_date(eng, "k", "2026-07-14")) == 2
    assert len(slots_for_date(eng, "k", "2026-07-15")) == 2


def test_plan_IDEMPOTENT(tmp_path):
    """Planlayıcı uygulama açılışında da koşuyor — kopya slot = KOPYA VİDEO."""
    eng = _eng(tmp_path)
    plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=2)
    assert plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=2) == 0


def test_autopilot_kapali_kanal_planlanmaz(tmp_path):
    class _Off(_Ch):
        class autopilot(_AP):
            enabled = False

    assert plan_channel(_eng(tmp_path), _Off(),
                        today_local=date(2026, 7, 14), days=2) == 0


def test_devre_disi_kanal_planlanmaz(tmp_path):
    class _Off(_Ch):
        enabled = False

    assert plan_channel(_eng(tmp_path), _Off(),
                        today_local=date(2026, 7, 14), days=2) == 0


# --- ÜRETİM ----------------------------------------------------------------

def test_lead_gelmeden_URETILMEZ(tmp_path):
    eng = _eng(tmp_path)
    _slot(eng, 13)                                   # slot 13:00, lead 3sa → 10:00
    d, c = _deps(datetime(2026, 7, 14, 9, 30, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["produce"] == []
    assert _durum(eng)["status"] == "planned"


def test_lead_gelince_URETILIR_ve_ZAMANLANIR(tmp_path):
    eng = _eng(tmp_path)
    _slot(eng, 13)
    sid = _gercek_short(eng)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid))
    tick(eng, _Ch(), d)
    assert c["produce"] == ["k"]
    s = _durum(eng)
    assert s["status"] == "scheduled", "publish_at modunda hemen zamanlanmalı"
    assert s["short_id"] == sid


def test_uretim_patlarsa_ATTEMPT_artar_ve_TEKRAR_denenir(tmp_path):
    eng = _eng(tmp_path)
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(status="failed", short_id=None,
                                      error="ai33 patladi"))
    tick(eng, _Ch(), d)
    s = _durum(eng)
    assert s["attempts"] == 1
    assert s["status"] == "planned", "tekrar denenebilmeli"
    assert "ai33" in s["error"]

    tick(eng, _Ch(), d)
    assert _durum(eng)["attempts"] == 2


def test_uretim_ISTISNA_atarsa_da_yakalanir(tmp_path):
    eng = _eng(tmp_path)
    _slot(eng, 13)

    def _patla():
        raise RuntimeError("beklenmedik cokme")

    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC), produce=_patla)
    tick(eng, _Ch(), d)
    s = _durum(eng)
    assert s["attempts"] == 1 and s["status"] == "planned"
    assert "cokme" in s["error"]


def test_MAX_ATTEMPT_sonra_FAILED_ve_bir_daha_denenmez(tmp_path):
    eng = _eng(tmp_path)
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(status="failed", short_id=None, error="x"))
    for _ in range(3):
        tick(eng, _Ch(), d)
    s = _durum(eng)
    assert s["status"] == "failed" and s["attempts"] == 3

    tick(eng, _Ch(), d)
    assert len(c["produce"]) == 3, "failed slot yeniden üretilmeye çalışıldı"


def test_slot_gecmisse_SKIPPED_ve_URETILMEZ(tmp_path):
    """Uygulama kapalıydı. GEÇ YÜKLEME YOK — 22:00'de yayınlanan gündüz videosu
    hedefi zaten ıskalar."""
    eng = _eng(tmp_path)
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 13, 30, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["produce"] == []
    assert _durum(eng)["status"] == "skipped"


def test_tick_bir_seferde_TEK_slot_uretir(tmp_path):
    """Pipeline kanal başına KİLİTLİ ve üretim ~15 dk sürüyor. İkinci üretimi aynı
    tick'te başlatmak onu 'lock busy' → failed yapar ve slot boşuna deneme harcar."""
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [
        {"slot_index": 0, "slot_at_utc": datetime(2026, 7, 14, 13, tzinfo=UTC),
         "jitter_min": 0, "kind": "series"},
        {"slot_index": 1, "slot_at_utc": datetime(2026, 7, 14, 14, tzinfo=UTC),
         "jitter_min": 0, "kind": "standalone"}])
    sid = _gercek_short(eng)
    d, c = _deps(datetime(2026, 7, 14, 11, 30, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid))
    tick(eng, _Ch(), d)
    assert len(c["produce"]) == 1


# --- YÜKLEME: publish_at MODU ----------------------------------------------

def test_publish_at_RFC3339_UTC_olarak_gecer(tmp_path):
    eng = _eng(tmp_path)
    _slot(eng, 13, 4)
    sid = _gercek_short(eng)
    d, c = _deps(datetime(2026, 7, 14, 10, 5, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid))
    tick(eng, _Ch(), d)
    assert len(c["sched"]) == 1
    short_id, publish_at = c["sched"][0]
    assert short_id == sid
    assert publish_at == "2026-07-14T13:04:00Z"


def test_publish_at_GECMISE_zamanlanamaz(tmp_path):
    """Üretim bitmiş ama slot anı geçmiş → publishAt geçersiz. YouTube REDDETMEZ,
    videoyu ANINDA yayınlar. Slotu düşür."""
    eng = _eng(tmp_path)
    s = _slot(eng, 13)
    sid = _gercek_short(eng)
    slot_set_status(eng, s["id"], "produced", short_id=sid)
    d, c = _deps(datetime(2026, 7, 14, 13, 30, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["sched"] == []
    assert _durum(eng)["status"] == "failed"
    assert "publishAt" in _durum(eng)["error"]


def test_yukleme_patlarsa_PRODUCED_ta_kalir_ve_tekrar_denenir(tmp_path):
    """'scheduled' işaretlersek panel 'yayına zamanlandı' der ama video hiç
    yüklenmemiştir — sessiz bozulma."""
    eng = _eng(tmp_path)
    _slot(eng, 13)
    sid = _gercek_short(eng)

    def _patla():
        raise RuntimeError("yt 503")

    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid), sched=_patla)
    tick(eng, _Ch(), d)
    assert _durum(eng)["status"] == "produced"

    d2, c2 = _deps(datetime(2026, 7, 14, 10, 10, tzinfo=UTC))
    tick(eng, _Ch(), d2)
    assert _durum(eng)["status"] == "scheduled"
    assert len(c2["sched"]) == 1


def test_slot_gecince_SCHEDULED_yayinlandi_sayilir(tmp_path):
    eng = _eng(tmp_path)
    s = _slot(eng, 13)
    sid = _gercek_short(eng)
    slot_set_status(eng, s["id"], "scheduled", short_id=sid)
    d, c = _deps(datetime(2026, 7, 14, 13, 5, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert _durum(eng)["status"] == "published"


# --- YÜKLEME: live_upload MODU ---------------------------------------------

def test_live_modda_slot_ANINDAN_ONCE_yuklenmez(tmp_path):
    eng = _eng(tmp_path)
    _slot(eng, 13)
    sid = _gercek_short(eng)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid))
    tick(eng, _Live(), d)
    assert c["produce"] == ["k"]
    assert c["live"] == [], "slot saatinden ÖNCE yükledi"
    assert _durum(eng)["status"] == "produced"


def test_live_modda_slot_ANINDA_yuklenir(tmp_path):
    eng = _eng(tmp_path)
    s = _slot(eng, 13)
    sid = _gercek_short(eng)
    slot_set_status(eng, s["id"], "produced", short_id=sid)
    d, c = _deps(datetime(2026, 7, 14, 13, 1, tzinfo=UTC))
    tick(eng, _Live(), d)
    assert c["live"] == [sid]
    assert _durum(eng)["status"] == "published"


def test_live_modda_GRACE_disinda_FAILED(tmp_path):
    """Uygulama slot anında kapalıydı ve çok geç açıldı. GEÇ YÜKLEME YOK."""
    eng = _eng(tmp_path)
    s = _slot(eng, 13)
    sid = _gercek_short(eng)
    slot_set_status(eng, s["id"], "produced", short_id=sid)
    gec = datetime(2026, 7, 14, 13, LIVE_GRACE_MIN + 5, tzinfo=UTC)
    d, c = _deps(gec)
    tick(eng, _Live(), d)
    assert c["live"] == []
    assert _durum(eng)["status"] == "failed"


# --- ARK YENİLEME ----------------------------------------------------------

def test_uretimden_ONCE_ark_saglanir(tmp_path):
    """Ark bitmişse yeni ark planlanıp oto-onaylanmalı — ÜRETİMDEN ÖNCE. Sonra
    yapılırsa bu bölüm bankadan TEK KONU olarak çıkar ve seri delinir."""
    eng = _eng(tmp_path)
    _slot(eng, 13)
    sid = _gercek_short(eng)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid))
    tick(eng, _Ch(), d)
    assert c["arc"] == ["k"]


def test_uretilecek_slot_yoksa_ark_da_cagrilmaz(tmp_path):
    """Boşuna LLM çağrısı yakmayalım."""
    eng = _eng(tmp_path)
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 9, 0, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["arc"] == []


def test_ark_patlarsa_uretim_YINE_kosar(tmp_path):
    """Ark KOZMETİK değil ama üretimi durdurmamalı."""
    eng = _eng(tmp_path)
    _slot(eng, 13)
    sid = _gercek_short(eng)

    def _patla():
        raise RuntimeError("LLM yok")

    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid), arc=_patla)
    tick(eng, _Ch(), d)
    assert c["produce"] == ["k"]
    assert _durum(eng)["status"] == "scheduled"


# --- KAPALI ----------------------------------------------------------------

def test_autopilot_kapaliyken_tick_HICBIR_SEY_yapmaz(tmp_path):
    class _Off(_Ch):
        class autopilot(_AP):
            enabled = False

    eng = _eng(tmp_path)
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC))
    assert tick(eng, _Off(), d) == {}
    assert c["produce"] == []
    assert _durum(eng)["status"] == "planned"


# --- KULLANICININ AYARI SON SÖZ --------------------------------------------
# GERÇEK HATA (uçtan uca doğrulamada bulundu): build_deps doğrudan run_auto_upload
# çağırıyordu — yani youtube.auto_upload=false olan bir kanalda bile YÜKLÜYORDU.
# Kullanıcının açıkça reddettiği bir şeyi yapmak: kanalına izinsiz video koymak.

class _YuklemeKapali(_Ch):
    class youtube:
        auto_upload = False


def test_auto_upload_KAPALIYKEN_autopilot_YUKLEMEZ(tmp_path):
    eng = _eng(tmp_path)
    _slot(eng, 13)
    sid = _gercek_short(eng)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid))
    tick(eng, _YuklemeKapali(), d)
    assert c["produce"] == ["k"], "üretim yine koşmalı"
    assert c["sched"] == [], "kullanıcı otomatik yüklemeyi KAPATMIŞ ama yüklendi"
    assert _durum(eng)["status"] == "produced", "video hazır, kullanıcı elle yükler"


def test_youtube_blogu_YOKSA_da_yuklemez(tmp_path):
    class _Yok(_Ch):
        youtube = None

    eng = _eng(tmp_path)
    _slot(eng, 13)
    sid = _gercek_short(eng)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(short_id=sid))
    tick(eng, _Yok(), d)
    assert c["sched"] == []
    assert _durum(eng)["status"] == "produced"


def test_live_modda_da_auto_upload_kapaliysa_yuklemez(tmp_path):
    class _LiveKapali(_Live):
        class youtube:
            auto_upload = False

    eng = _eng(tmp_path)
    s = _slot(eng, 13)
    sid = _gercek_short(eng)
    slot_set_status(eng, s["id"], "produced", short_id=sid)
    d, c = _deps(datetime(2026, 7, 14, 13, 1, tzinfo=UTC))
    tick(eng, _LiveKapali(), d)
    assert c["live"] == []
    assert _durum(eng)["status"] == "produced"
