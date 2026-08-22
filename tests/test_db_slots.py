"""Slot tablosu: sistemin TEK doğruluk kaynağı.

"Bugün ne üretilecek, ne zaman yayınlanacak, hangisi patladı" — hepsinin cevabı burada.

Planlama İDEMPOTENT olmak ZORUNDA: planlayıcı hem gece cron'unda hem uygulama
açılışında koşuyor. Kopya slot = KOPYA VİDEO, ve bu hiçbir hata vermez.
"""
from datetime import date, datetime, timezone

from short_bot.db import (init_db, open_slots, plan_slots, prev_day_jitters,
                          record_short, slot_bump_attempt, slot_set_status,
                          slots_for_date, slots_in_range, start_run)

UTC = timezone.utc


def _slot(i, hour):
    return {"slot_index": i,
            "slot_at_utc": datetime(2026, 7, 14, hour, 0, tzinfo=UTC),
            "jitter_min": i * 2}


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _short(eng, ch="k") -> int:
    """GERÇEK short satırı. slot.short_id bir FOREIGN KEY — uydurma id kabul edilmez,
    ve bu iyi: hayalet bir short'a bağlı slot, panelde 'videoyu aç' deyip 404 verirdi."""
    return record_short(eng, channel=ch, rss_item_guid=None, title="Baslik",
                        file_path="out/v.mp4", duration_s=40,
                        script_json="{}", render_ms=1000)


def _run(eng, ch="k") -> int:
    return start_run(eng, ch, trigger="test", log_path="x.log")


def test_plan_ve_oku(tmp_path):
    eng = _eng(tmp_path)
    n = plan_slots(eng, "k", "2026-07-14", [_slot(0, 10), _slot(1, 14)])
    assert n == 2
    s = slots_for_date(eng, "k", "2026-07-14")
    assert [x["slot_index"] for x in s] == [0, 1]
    assert all(x["status"] == "planned" for x in s)
    assert s[0]["attempts"] == 0
    assert s[1]["jitter_min"] == 2


def test_planlama_IDEMPOTENT(tmp_path):
    """Uygulama her açılışta planlıyor. Kopya slot = KOPYA VİDEO."""
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10), _slot(1, 14)])
    eklenen = plan_slots(eng, "k", "2026-07-14", [_slot(0, 10), _slot(1, 14)])
    assert eklenen == 0, "aynı gün ikinci kez planlandı → kopya slot"
    assert len(slots_for_date(eng, "k", "2026-07-14")) == 2


def test_planlama_MEVCUT_slotu_EZMEZ(tmp_path):
    """Üretilmiş bir slot yeniden planlanırsa durumu sıfırlanır ve video İKİ KEZ
    üretilip İKİ KEZ yüklenir. Geri dönüşü olmayan, sessiz bir bozulma."""
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    sid = slots_for_date(eng, "k", "2026-07-14")[0]["id"]
    short_id = _short(eng)
    slot_set_status(eng, sid, "published", short_id=short_id)

    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["status"] == "published", "planlama üretilmiş slotu sıfırladı"
    assert s["short_id"] == short_id


def test_eksik_slot_EKLENIR_mevcutlara_dokunmadan(tmp_path):
    """daily_count 1'den 3'e çıkarılırsa eksikler eklenmeli, var olan korunmalı."""
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    short_id = _short(eng)
    slot_set_status(eng, slots_for_date(eng, "k", "2026-07-14")[0]["id"],
                    "produced", short_id=short_id)

    n = plan_slots(eng, "k", "2026-07-14", [_slot(0, 10), _slot(1, 14), _slot(2, 18)])
    assert n == 2
    s = slots_for_date(eng, "k", "2026-07-14")
    assert len(s) == 3
    assert s[0]["status"] == "produced" and s[0]["short_id"] == short_id


def test_kanallar_karismaz(tmp_path):
    eng = _eng(tmp_path)
    plan_slots(eng, "a", "2026-07-14", [_slot(0, 10)])
    plan_slots(eng, "b", "2026-07-14", [_slot(0, 10)])
    assert len(slots_for_date(eng, "a", "2026-07-14")) == 1
    assert len(slots_for_date(eng, "b", "2026-07-14")) == 1


def test_durum_ve_alanlar_yazilir(tmp_path):
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    sid = slots_for_date(eng, "k", "2026-07-14")[0]["id"]

    slot_set_status(eng, sid, "producing")
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "producing"

    short_id, run_id = _short(eng), _run(eng)
    slot_set_status(eng, sid, "produced", short_id=short_id, run_id=run_id)
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["status"] == "produced"
    assert s["short_id"] == short_id and s["run_id"] == run_id
    assert s["produced_at"] is not None

    slot_set_status(eng, sid, "scheduled")
    assert slots_for_date(eng, "k", "2026-07-14")[0]["uploaded_at"] is not None

    slot_set_status(eng, sid, "failed", error="ai33 patladi")
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["status"] == "failed" and "ai33" in s["error"]


def test_attempt_sayaci(tmp_path):
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    sid = slots_for_date(eng, "k", "2026-07-14")[0]["id"]
    assert slot_bump_attempt(eng, sid) == 1
    assert slot_bump_attempt(eng, sid) == 2
    assert slots_for_date(eng, "k", "2026-07-14")[0]["attempts"] == 2


def test_ACIK_slotlar_sonuclananları_getirmez(tmp_path):
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10), _slot(1, 14), _slot(2, 18)])
    s = slots_for_date(eng, "k", "2026-07-14")
    slot_set_status(eng, s[0]["id"], "published")
    slot_set_status(eng, s[1]["id"], "failed", error="x")

    acik = open_slots(eng, "k")
    assert [x["slot_index"] for x in acik] == [2]


def test_onceki_gunun_jitterlari(tmp_path):
    """Rastgele yürüyüş dünkü sapmadan devam eder. Okunamazsa her gün 0'dan başlar
    ve slotlar tabana yapışır: ritim ölür."""
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-13", [
        {"slot_index": 0, "slot_at_utc": datetime(2026, 7, 13, 10, tzinfo=UTC),
         "jitter_min": 7},
        {"slot_index": 1, "slot_at_utc": datetime(2026, 7, 13, 14, tzinfo=UTC),
         "jitter_min": -4}])
    assert prev_day_jitters(eng, "k", date(2026, 7, 14)) == {0: 7, 1: -4}


def test_onceki_gun_yoksa_bos(tmp_path):
    assert prev_day_jitters(_eng(tmp_path), "k", date(2026, 7, 14)) == {}


def test_aralik_sorgusu(tmp_path):
    eng = _eng(tmp_path)
    for g in ("2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"):
        plan_slots(eng, "k", g, [_slot(0, 10)])
    r = slots_in_range(eng, "k", "2026-07-14", "2026-07-15")
    assert {x["slot_local_date"] for x in r} == {"2026-07-14", "2026-07-15"}
