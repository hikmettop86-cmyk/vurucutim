"""Ark oto-yenileme.

Günde 3 video üreten bir kanalda 3 bölümlük ark BİR GÜNDE biter. Ertesi gün onaylı ark
kalmazsa seri DURUR ve kanal "numaralı ama birbiriyle ilgisiz videolar" üretmeye başlar
— bu, seri olmamaktan da kötüdür: izleyiciye verilmiş söz tutulmaz.

Kullanıcının kararı: otomatik planla + otomatik ONAYLA. TEK İSTİSNA: kullanıcının
kendi bekleyen taslağı varsa DOKUNMA.
"""
from short_bot.autopilot_arc import ensure_arc
from short_bot.db import (active_arc, all_bank_topics, approve_arc, create_arc,
                          draft_arc, init_db, insert_bank_topics)


class _Reel:
    enabled = True
    series_enabled = True
    arc_mode = "planned"
    series_arc_length = 3


class _Ch:
    slug = "k"
    name = "Kanal"
    reel = _Reel()
    generator = None


_PLAN = [{"topic": "Bir konu", "promise": ""},
         {"topic": "Iki konu", "promise": "vaat"}]


def _fake_plan(monkeypatch, ok=True):
    import short_bot.autopilot_arc as A

    class _E:
        def __init__(self, t, p):
            self.topic = t
            self.promise = p

    class _P:
        title = "Yeni Ark"
        episodes = [_E(e["topic"], e["promise"]) for e in _PLAN]

    monkeypatch.setattr(A, "plan_arc", (lambda *a, **kw: _P()) if ok
                        else (lambda *a, **kw: None))


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _banka(eng):
    insert_bank_topics(eng, "k", [{"topic": "Bankadaki konu", "views": 1, "subs": 1}])


def test_aktif_ark_varsa_DOKUNMAZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)
    eng = _eng(tmp_path)
    aid = create_arc(eng, "k", title="Mevcut", seed_topic="t", plan=_PLAN)
    approve_arc(eng, aid)
    assert ensure_arc(eng, _Ch(), llm_call=object()) is False
    assert active_arc(eng, "k")["id"] == aid


def test_KULLANICININ_taslagi_varsa_OTO_ONAYLAMAZ(tmp_path, monkeypatch):
    """Kullanıcının incelemesini ezmek, onay mekanizmasına duyduğu güveni yıkar."""
    _fake_plan(monkeypatch)
    eng = _eng(tmp_path)
    _banka(eng)
    aid = create_arc(eng, "k", title="Kullanicinin taslagi", seed_topic="t", plan=_PLAN)
    assert ensure_arc(eng, _Ch(), llm_call=object()) is False
    assert active_arc(eng, "k") is None, "kullanıcının taslağı oto-onaylandı"
    assert draft_arc(eng, "k")["id"] == aid


def test_ark_yoksa_PLANLAR_ve_ONAYLAR(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)
    eng = _eng(tmp_path)
    _banka(eng)
    assert ensure_arc(eng, _Ch(), llm_call=object()) is True
    a = active_arc(eng, "k")
    assert a is not None, "ark planlanmadı"
    assert a["title"] == "Yeni Ark"
    assert a["status"] == "active", "ark oto-onaylanmadı → seri durur"
    assert a["seed_topic"] == "Bankadaki konu"


def test_tohum_bankadan_DUSER(tmp_path, monkeypatch):
    """Aynı tohumdan iki ark planlanmasın."""
    _fake_plan(monkeypatch)
    eng = _eng(tmp_path)
    _banka(eng)
    ensure_arc(eng, _Ch(), llm_call=object())
    assert all_bank_topics(eng, "k")[0]["status"] == "used"


def test_banka_bossa_COKMEZ(tmp_path, monkeypatch):
    """Tohum yoksa ark kurulamaz — ama üretim yine koşmalı (LLM konu üretir)."""
    _fake_plan(monkeypatch)
    eng = _eng(tmp_path)
    assert ensure_arc(eng, _Ch(), llm_call=object()) is False
    assert active_arc(eng, "k") is None


def test_LLM_patlarsa_COKMEZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch, ok=False)
    eng = _eng(tmp_path)
    _banka(eng)
    assert ensure_arc(eng, _Ch(), llm_call=object()) is False
    assert active_arc(eng, "k") is None


def test_LLM_yoksa_COKMEZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)
    eng = _eng(tmp_path)
    _banka(eng)
    assert ensure_arc(eng, _Ch(), llm_call=None) is False


def test_zincir_modunda_DOKUNMAZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)

    class _C(_Ch):
        class reel(_Reel):
            arc_mode = "chain"

    eng = _eng(tmp_path)
    _banka(eng)
    assert ensure_arc(eng, _C(), llm_call=object()) is False
    assert active_arc(eng, "k") is None


def test_seri_kapaliysa_DOKUNMAZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)

    class _C(_Ch):
        class reel(_Reel):
            series_enabled = False

    eng = _eng(tmp_path)
    _banka(eng)
    assert ensure_arc(eng, _C(), llm_call=object()) is False


def test_reel_olmayan_kanalda_DOKUNMAZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)

    class _C(_Ch):
        reel = None

    eng = _eng(tmp_path)
    _banka(eng)
    assert ensure_arc(eng, _C(), llm_call=object()) is False
