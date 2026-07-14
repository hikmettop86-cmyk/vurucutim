"""Panel yeniden başlatılınca UÇUŞTAKİ ÜRETİM ÖLÜR — enkazı toplayan yok.

GERÇEK OLAY (2026-07-14, ölçüldü):
    15:25:18  vucudun-gizli-onarim-gucu üretimi başladı (otomasyon slotu)
    15:34:19  son log satırı
    15:34:32  panel yeniden başlatıldı (kod değişikliği yüklemek için)
              → üretim thread'i panelle birlikte öldü

Geriye kalan enkaz:
    runs.id=888              status='running'    → sonsuza dek öyle
    publish_slots.id=13      status='producing'  → otomasyon bir daha ELE ALMIYOR
    data/locks/<slug>.lock   sahipsiz

Panel "Aşama 4/8" gösterip duruyordu. Kullanıcı "takılmış olabilir" dedi — haklıydı.

NEDEN TEMİZLENMEDİ: cleanup_zombie_runs açılışta koşuyor ama `age_minutes=60`
şartıyla. Ölen koşu o an 9 DAKİKALIKTI. Ve periyodik süpürücü yok → satır kalıcı.

DOĞRU ÖLÇÜT YAŞ DEĞİL, CANLILIK: açılışta, kilidi SERBEST olan bir 'running' satırının
sahibi kesinlikle ölüdür (önceki sürecin thread'i hayatta olamaz). Kilit hâlâ
tutuluyorsa canlı bir üretim vardır — ona dokunulmaz.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock
from sqlalchemy import select

from short_bot.db import (cleanup_zombie_runs, finish_run, init_db, plan_slots,
                          publish_slots, reclaim_producing_slots, runs,
                          slot_set_status, start_run)

UTC = timezone.utc


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _kilitler(tmp_path):
    d = tmp_path / "locks"
    d.mkdir(exist_ok=True)
    return d


# --- ZOMBİ KOŞULAR ---------------------------------------------------------

def test_KILIDI_SERBEST_kosu_YASINA_BAKILMADAN_temizlenir(tmp_path):
    """9 DAKİKALIK zombi. Eski kural (>60 dk) bunu kaçırıyordu — gerçek olay buydu."""
    eng = _eng(tmp_path)
    kilit = _kilitler(tmp_path)
    rid = start_run(eng, "k", trigger="autopilot", log_path="x.log")
    (kilit / "k.lock").touch()          # sahipsiz kilit (süreç öldü)

    assert cleanup_zombie_runs(eng, kilit) == 1
    with eng.connect() as c:
        r = c.execute(select(runs).where(runs.c.id == rid)).mappings().one()
    assert r["status"] == "failed"
    assert "panel" in (r["error"] or "").lower() or "zombi" in (r["error"] or "").lower()
    assert not (kilit / "k.lock").exists(), "sahipsiz kilit silinmedi"


def test_KILIDI_TUTULAN_kosuya_DOKUNULMAZ(tmp_path):
    """CANLI üretim. Bunu 'failed' işaretlemek çalışan bir işi öldürmek olurdu."""
    eng = _eng(tmp_path)
    kilit = _kilitler(tmp_path)
    rid = start_run(eng, "k", trigger="manual", log_path="x.log")

    with FileLock(str(kilit / "k.lock"), timeout=0):
        assert cleanup_zombie_runs(eng, kilit) == 0
    with eng.connect() as c:
        r = c.execute(select(runs).where(runs.c.id == rid)).mappings().one()
    assert r["status"] == "running", "CANLI üretim öldürüldü"


def test_kilit_TUTULUYOR_ama_COK_ESKIYSE_temizlenir(tmp_path):
    """Gerçekten asılı kalmış (süreç canlı, üretim ilerlemiyor) → yaş kuralı devrede."""
    eng = _eng(tmp_path)
    kilit = _kilitler(tmp_path)
    rid = start_run(eng, "k", trigger="manual", log_path="x.log")
    eski = datetime.now(UTC) - timedelta(minutes=120)
    with eng.begin() as c:
        c.execute(runs.update().where(runs.c.id == rid)
                  .values(started_at=eski.replace(tzinfo=None)))

    with FileLock(str(kilit / "k.lock"), timeout=0):
        assert cleanup_zombie_runs(eng, kilit, age_minutes=60) == 1


def test_BITMIS_kosulara_dokunulmaz(tmp_path):
    eng = _eng(tmp_path)
    kilit = _kilitler(tmp_path)
    rid = start_run(eng, "k", trigger="manual", log_path="x.log")
    finish_run(eng, rid, status="success")
    assert cleanup_zombie_runs(eng, kilit) == 0


# --- ÖKSÜZ SLOTLAR ---------------------------------------------------------

def test_PRODUCING_slot_acilista_GERI_ALINIR(tmp_path):
    """SESSİZ KAYIP: üretim thread'i panelle öldü, slot 'producing'de kaldı ve
    otomasyon onu BİR DAHA ELE ALMADI. Günün videosu yok oldu, kimse söylemedi."""
    eng = _eng(tmp_path)
    yarin = datetime.now(UTC) + timedelta(hours=3)
    plan_slots(eng, "k", "2026-07-14",
               [{"slot_index": 0, "slot_at_utc": yarin, "jitter_min": 0,
                 "kind": "standalone"}])
    with eng.connect() as c:
        sid = c.execute(select(publish_slots.c.id)).scalar()
    slot_set_status(eng, sid, "producing")

    assert reclaim_producing_slots(eng) == 1
    with eng.connect() as c:
        s = c.execute(select(publish_slots).where(publish_slots.c.id == sid)) \
            .mappings().one()
    assert s["status"] == "planned", "slot geri alınmadı → o video hiç üretilmeyecek"


def test_geri_alinan_slot_DENEME_sayacini_korur(tmp_path):
    """max_attempts sınırı ayakta kalmalı — sonsuz döngü olmasın."""
    from short_bot.db import slot_bump_attempt
    eng = _eng(tmp_path)
    yarin = datetime.now(UTC) + timedelta(hours=3)
    plan_slots(eng, "k", "2026-07-14",
               [{"slot_index": 0, "slot_at_utc": yarin, "jitter_min": 0,
                 "kind": "standalone"}])
    with eng.connect() as c:
        sid = c.execute(select(publish_slots.c.id)).scalar()
    slot_bump_attempt(eng, sid)
    slot_set_status(eng, sid, "producing")

    reclaim_producing_slots(eng)
    with eng.connect() as c:
        s = c.execute(select(publish_slots).where(publish_slots.c.id == sid)) \
            .mappings().one()
    assert s["attempts"] == 1, "deneme sayacı sıfırlandı → sonsuz yeniden deneme riski"


def test_URETILMIS_slota_dokunulmaz(tmp_path):
    """'produced' / 'uploaded' / 'published' geçmiştir — yeniden yazılmaz."""
    eng = _eng(tmp_path)
    yarin = datetime.now(UTC) + timedelta(hours=3)
    plan_slots(eng, "k", "2026-07-14",
               [{"slot_index": i, "slot_at_utc": yarin, "jitter_min": 0,
                 "kind": "standalone"} for i in range(3)])
    with eng.connect() as c:
        ids = [r[0] for r in c.execute(select(publish_slots.c.id)).all()]
    slot_set_status(eng, ids[0], "produced")
    slot_set_status(eng, ids[1], "published")
    # ids[2] planned kalır

    assert reclaim_producing_slots(eng) == 0
    with eng.connect() as c:
        durum = {r["id"]: r["status"] for r in
                 c.execute(select(publish_slots)).mappings()}
    assert durum[ids[0]] == "produced"
    assert durum[ids[1]] == "published"
    assert durum[ids[2]] == "planned"
