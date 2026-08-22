"""Seri bölümleri: ark zinciri ÜRETİMLER ARASINDA yaşamalı.

Bölüm numarası ve ödenecek söz, süreç ömrünü aşan durumdur — bu tablo olmadan
zincir kurulamaz. Testler zincirin GERÇEKTEN döndüğünü ölçüyor: bir bölümün açtığı
kapı, bir sonraki bölümün konusu oluyor mu?
"""
from short_bot.db import episode_history, init_db, last_episode, record_episode
from short_bot.reel_series import plan_episode


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def test_bos_kanalda_bolum_yok(tmp_path):
    assert last_episode(_eng(tmp_path), "kanal") is None


def test_kayit_ve_geri_okuma(tmp_path):
    eng = _eng(tmp_path)
    record_episode(eng, "kanal", episode_no=1, arc_pos=1, topic="fener balığı",
                   open_loop="O ışığı üreten şey ne?", short_id=None)
    son = last_episode(eng, "kanal")
    assert son["episode_no"] == 1
    assert son["open_loop"] == "O ışığı üreten şey ne?"
    assert son["topic"] == "fener balığı"


def test_ZINCIR_gercekten_donuyor(tmp_path):
    """Bu modülün varlık sebebi: kapı → sonraki bölümün konusu."""
    eng = _eng(tmp_path)
    kapilar = ["O ışığı üreten şey ne?", "Peki o bakteri oraya nasıl gitti?",
               "Ve neden sadece bu türde?"]
    son = None
    konular = []
    for kapi in kapilar:
        p = plan_episode(last_episode(eng, "kanal"), arc_max=5)
        konular.append(p.continue_from)
        record_episode(eng, "kanal", episode_no=p.episode_no, arc_pos=p.arc_pos,
                       topic=(p.continue_from or "ilk konu"), open_loop=kapi)
        son = p
    # 1. bölümün konusu bankadan (continue_from boş), 2. ve 3. ÖNCEKİ KAPIDAN gelmeli
    assert konular[0] == ""
    assert konular[1] == kapilar[0]
    assert konular[2] == kapilar[1]
    assert son.episode_no == 3 and son.arc_pos == 3


def test_ark_dolunca_zincir_kesilir_numara_devam_eder(tmp_path):
    eng = _eng(tmp_path)
    for i in range(4):
        p = plan_episode(last_episode(eng, "kanal"), arc_max=2)
        record_episode(eng, "kanal", episode_no=p.episode_no, arc_pos=p.arc_pos,
                       topic="k", open_loop="bir kapı")
    gecmis = episode_history(eng, "kanal")
    assert [g["episode_no"] for g in gecmis] == [4, 3, 2, 1]
    # arc_max=2 → ark pozisyonları 1,2,1,2 olmalı (her iki bölümde bir zincir kesilir)
    assert [g["arc_pos"] for g in sorted(gecmis, key=lambda g: g["episode_no"])] == [1, 2, 1, 2]


def test_siralama_EPISODE_NO_ya_gore_created_at_e_degil(tmp_path):
    """İki üretim aynı saniyede biterse created_at eşitlenir ve zincir yanlış
    halkadan devam edebilir. Sıralama numaraya bağlı olmalı."""
    eng = _eng(tmp_path)
    record_episode(eng, "kanal", episode_no=1, arc_pos=1, topic="a", open_loop="k1")
    record_episode(eng, "kanal", episode_no=2, arc_pos=2, topic="b", open_loop="k2")
    record_episode(eng, "kanal", episode_no=3, arc_pos=3, topic="c", open_loop="k3")
    assert last_episode(eng, "kanal")["episode_no"] == 3


def test_kanallar_birbirinin_zincirine_karismaz(tmp_path):
    eng = _eng(tmp_path)
    record_episode(eng, "a", episode_no=9, arc_pos=1, topic="x", open_loop="ka")
    record_episode(eng, "b", episode_no=1, arc_pos=1, topic="y", open_loop="kb")
    assert last_episode(eng, "a")["episode_no"] == 9
    assert last_episode(eng, "b")["episode_no"] == 1
    assert last_episode(eng, "b")["open_loop"] == "kb"


def test_kapisiz_bolum_arki_bitirir(tmp_path):
    eng = _eng(tmp_path)
    record_episode(eng, "kanal", episode_no=5, arc_pos=2, topic="x", open_loop="")
    p = plan_episode(last_episode(eng, "kanal"), arc_max=5)
    assert p.episode_no == 6
    assert p.continue_from == "", "kapı yoksa zincirlenecek bir şey de yok"
    assert p.arc_pos == 1
