"""Planlı arkın kalıcı durumu: taslak → onay → bölüm bölüm tüketim.

En kritik davranış: TASLAK ÜRETİME GİRMEZ. Kullanıcı görmeden hiçbir ark üretilmeye
başlamazsa, "otomasyon nereye gidiyor bilmiyorum" sorunu ortadan kalkar.
"""
from short_bot.db import (active_arc, advance_arc, approve_arc, arc_history,
                          create_arc, discard_arc, draft_arc, init_db)

_PLAN = [{"topic": "Bir", "promise": ""},
         {"topic": "Iki", "promise": "Ikinin vaadi"},
         {"topic": "Uc", "promise": "Ucun vaadi"}]


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def test_TASLAK_uretime_GIRMEZ(tmp_path):
    """Modülün varlık sebebi: onaylanmamış ark üretilmez."""
    eng = _eng(tmp_path)
    create_arc(eng, "k", title="Ark", seed_topic="tohum", plan=_PLAN)
    assert draft_arc(eng, "k") is not None
    assert active_arc(eng, "k") is None, "taslak AKTİF sayılıyor → onaysız üretilir"


def test_onaylanan_ark_aktif_olur(tmp_path):
    eng = _eng(tmp_path)
    aid = create_arc(eng, "k", title="Ark", seed_topic="t", plan=_PLAN)
    approve_arc(eng, aid)
    a = active_arc(eng, "k")
    assert a is not None and a["id"] == aid
    assert a["total"] == 3 and a["produced"] == 0 and a["remaining"] == 3
    assert draft_arc(eng, "k") is None, "onaylanan ark artık taslak değil"


def test_sayac_bolum_bolum_ilerler_ve_biter(tmp_path):
    eng = _eng(tmp_path)
    aid = create_arc(eng, "k", title="Ark", seed_topic="t", plan=_PLAN)
    approve_arc(eng, aid)
    for beklenen in (2, 1, 0):
        advance_arc(eng, aid)
        a = active_arc(eng, "k")
        if beklenen:
            assert a["remaining"] == beklenen
        else:
            assert a is None, "plan bitti → aktif ark kalmamalı"


def test_iki_aktif_ark_olamaz(tmp_path):
    """İki aktif ark olursa hangisinin üretileceği belirsizleşir."""
    eng = _eng(tmp_path)
    a1 = create_arc(eng, "k", title="A", seed_topic="t", plan=_PLAN)
    approve_arc(eng, a1)
    a2 = create_arc(eng, "k", title="B", seed_topic="t", plan=_PLAN)
    approve_arc(eng, a2)
    a = active_arc(eng, "k")
    assert a["id"] == a2, "yeni onaylanan ark aktif olmalı"
    # Eskisi done'a çekilmiş olmalı → tek aktif
    assert len([x for x in arc_history(eng, "k") if x["status"] == "active"]) == 1


def test_silinen_ark_gorunmez(tmp_path):
    eng = _eng(tmp_path)
    aid = create_arc(eng, "k", title="A", seed_topic="t", plan=_PLAN)
    discard_arc(eng, aid)
    assert draft_arc(eng, "k") is None
    assert active_arc(eng, "k") is None
    assert arc_history(eng, "k") == [], "silinen ark geçmişte de görünmemeli"


def test_kanallar_birbirinin_arkini_gormez(tmp_path):
    eng = _eng(tmp_path)
    a = create_arc(eng, "a", title="A", seed_topic="t", plan=_PLAN)
    approve_arc(eng, a)
    assert active_arc(eng, "b") is None
    assert draft_arc(eng, "b") is None


def test_plan_JSON_olarak_geri_gelir(tmp_path):
    eng = _eng(tmp_path)
    aid = create_arc(eng, "k", title="Ark", seed_topic="t", plan=_PLAN)
    approve_arc(eng, aid)
    a = active_arc(eng, "k")
    assert [e["topic"] for e in a["plan"]] == ["Bir", "Iki", "Uc"]
    assert a["plan"][1]["promise"] == "Ikinin vaadi"
