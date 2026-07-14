"""refresh_topic_bank uçtan uca — YENİ AKIŞ.

    kanıt   = madencilik (API anahtarı VARSA; yoksa [])
    konular = propose_topics(niş, kanıt=kanıt, mevcut=banka)
    yargı   = verify_topics(konular)          ← DOĞRULAMA KAPISI
    taze    = fuzzy-dedup(yargıyı geçenler)
    insert

API ANAHTARI VE REFERANS KANAL ARTIK İKİSİ DE OPSİYONEL. Banka asla kurumaz.
"""
import pytest

from short_bot.db import all_bank_topics, init_db, insert_bank_topics
from short_bot.topic_miner import refresh_topic_bank


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _llm(topics, verdicts=None):
    """Sahte Sonnet. İlk çağrı ÖNERİ, ikinci çağrı YARGI — şemadan ayırt ediyoruz."""
    def _f(prompt, schema, **kw):
        alanlar = schema.model_json_schema().get("properties", {})
        if "verdicts" in alanlar:
            v = verdicts if verdicts is not None else [
                {"index": i, "solid": True} for i in range(len(topics))]
            return schema.model_validate({"verdicts": v})
        return schema.model_validate({"topics": topics})
    return _f


def _k(t, src="", views=0, subs=0):
    return {"topic": t, "source_title": src, "views": views, "subs": subs,
            "hook_pattern": ""}


def test_API_ANAHTARI_YOKKEN_banka_dolar(tmp_path):
    """ESKİDEN: RuntimeError('YouTube API anahtarı yok') → banka HİÇ dolmuyordu."""
    eng = _eng(tmp_path)
    res = refresh_topic_bank(
        eng, "k", "insan vucudu", language="tr", api_keys=[],
        llm=_llm([_k("Mide ic zari 3-4 gunde bir yenilenir")]))
    assert res["added"] == 1
    rows = all_bank_topics(eng, "k")
    assert rows[0]["source"] == "llm", "kanıtsız konu dürüstçe etiketlenmeli"


def test_madencilik_PATLASA_da_banka_dolar(tmp_path, monkeypatch):
    """Kota doldu / ağ gitti → üretim yine koşar (kanıtsız), loglanır."""
    import short_bot.topic_miner as M

    def _patla(*a, **kw):
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(M, "mine_evidence", _patla)
    eng = _eng(tmp_path)
    res = refresh_topic_bank(
        eng, "k", "insan vucudu", language="tr", api_keys=["K"],
        llm=_llm([_k("DNA gunde 10 bin kez hasar gorur")]))
    assert res["added"] == 1


def test_TAZE_OUTLIER_YOKSA_uretim_kosar(tmp_path, monkeypatch):
    """ESKİDEN: ValueError('TAZE outlier bulunamadı') → madencilik TAMAMEN duruyordu."""
    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    res = refresh_topic_bank(
        eng, "k", "insan vucudu", language="tr", api_keys=["K"],
        llm=_llm([_k("Kornea 24 saatte kendini onarir")]))
    assert res["added"] == 1


def test_KANIT_VARSA_konuya_TASINIR(tmp_path, monkeypatch):
    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [
        {"source_title": "Kalbin elektrigi", "views": 900_000, "subs": 12_000,
         "ratio": 75.0, "video_id": "v1", "ref": False}])
    eng = _eng(tmp_path)
    refresh_topic_bank(
        eng, "k", "x", language="tr", api_keys=["K"],
        llm=_llm([_k("Kalp kendi elektrigini uretir", "Kalbin elektrigi",
                     900_000, 12_000)]))
    r = all_bank_topics(eng, "k")[0]
    assert r["source"] == "search"
    assert r["views"] == 900_000


def test_DOGRULAMADAN_DUSEN_konu_BANKAYA_GIRMEZ(tmp_path, monkeypatch):
    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    res = refresh_topic_bank(
        eng, "k", "x", language="tr", api_keys=[],
        llm=_llm([_k("Ici bos genelleme"), _k("Saglam somut olgu burada")],
                 verdicts=[{"index": 0, "solid": False, "reason": "içi boş"},
                           {"index": 1, "solid": True}]))
    assert res["added"] == 1
    assert res["rejected"] == 1
    assert [r["topic"] for r in all_bank_topics(eng, "k")] == \
        ["Saglam somut olgu burada"]


def test_HEPSI_DUSERSE_sifir_eklenir_ve_UYARILIR(tmp_path, monkeypatch, caplog):
    import logging

    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    with caplog.at_level(logging.WARNING):
        res = refresh_topic_bank(
            eng, "k", "x", language="tr", api_keys=[],
            llm=_llm([_k("Cop konu")],
                     verdicts=[{"index": 0, "solid": False, "reason": "boş"}]))
    assert res["added"] == 0
    assert "doğrulamayı geçmedi" in caplog.text, "sessizce sıfır eklendi"


def test_MUKERRER_konu_elenir(tmp_path, monkeypatch):
    """fuzzy-dedup regresyon kalkanı."""
    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    insert_bank_topics(eng, "k", [
        {"topic": "Karaciger kendini 3 haftada yeniler", "source_title": "V",
         "views": 1, "subs": 1}])
    res = refresh_topic_bank(
        eng, "k", "x", language="tr", api_keys=[],
        llm=_llm([_k("Karaciger kendini 3 haftada yeniler.")]))
    assert res["added"] == 0
    assert res["skipped_dup"] == 1


def test_MEVCUT_konular_ONERICIYE_verilir(tmp_path, monkeypatch):
    """Model tekrar üretmesin diye bankadakiler prompt'a girer."""
    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    insert_bank_topics(eng, "k", [
        {"topic": "Zaten bankada olan konu", "source_title": "V",
         "views": 1, "subs": 1}])
    gorulen = {}

    def _llm2(prompt, schema, **kw):
        alanlar = schema.model_json_schema().get("properties", {})
        if "verdicts" in alanlar:
            return schema.model_validate({"verdicts": [{"index": 0, "solid": True}]})
        gorulen["p"] = prompt
        return schema.model_validate({"topics": [_k("Yepyeni konu burada")]})

    refresh_topic_bank(eng, "k", "x", language="tr", api_keys=[], llm=_llm2)
    assert "Zaten bankada olan konu" in gorulen["p"]


def test_LLM_YOKSA_hata(tmp_path):
    """MEKANİK FALLBACK YOK."""
    eng = _eng(tmp_path)
    with pytest.raises(RuntimeError, match="konu üretilemedi"):
        refresh_topic_bank(eng, "k", "x", language="tr", api_keys=[], llm=None)
