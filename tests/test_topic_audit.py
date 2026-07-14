"""Mevcut bankadaki çöpü denetle.

ÖLÇÜLDÜ: vucudun-gizli-onarim-gucu bankasının 27 aktif konusundan 23'ü çöp (%85);
bazıları bilimsel olarak YANLIŞ ("muz saniyeler içinde sindirilir" — saatler sürer).
Bunlar üretilmeyi bekliyordu.
"""
from short_bot.db import all_bank_topics, init_db, insert_bank_topics
from short_bot.topic_audit import audit_bank


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _doldur(eng, konular):
    insert_bank_topics(eng, "k", [
        {"topic": t, "source_title": f"V{i}", "views": 1, "subs": 1}
        for i, t in enumerate(konular)])


def _llm(verdicts):
    def _f(prompt, schema, **kw):
        return schema.model_validate({"verdicts": verdicts})
    return _f


def _llm_metne_bakan(cop_anahtari: str):
    """Prompt'u GERÇEKTEN okuyup yargı veren sahte model.

    `all_bank_topics` en yeniyi önce döndürüyor — ekleme sırasını değil. Yargıyı sabit
    indekslere bağlamak testi kırılgan yapar ve YANLIŞ konuyu reddettiğimizi
    gizleyebilir (nitekim ilk yazışımda tam bu oldu).
    """
    def _f(prompt, schema, **kw):
        yargilar = []
        for satir in prompt.splitlines():
            s = satir.strip()
            if not s or "." not in s:
                continue
            bas, _, metin = s.partition(".")
            if not bas.isdigit():
                continue
            cop = cop_anahtari.lower() in metin.lower()
            yargilar.append({"index": int(bas), "solid": not cop,
                             "reason": "içi boş" if cop else ""})
        return schema.model_validate({"verdicts": yargilar})
    return _f


def test_COP_konular_REJECTED_isaretlenir(tmp_path):
    eng = _eng(tmp_path)
    _doldur(eng, ["Ici bos genelleme", "Saglam somut olgu"])
    res = audit_bank(eng, "k", language="tr", llm=_llm_metne_bakan("Ici bos"))
    assert res == {"checked": 2, "rejected": 1}
    durum = {r["topic"]: r["status"] for r in all_bank_topics(eng, "k")}
    assert durum["Ici bos genelleme"] == "rejected"
    assert durum["Saglam somut olgu"] == "active"


def test_KULLANILMIS_konulara_dokunulmaz(tmp_path):
    """'used' konular geçmiştir; video zaten üretildi, reddetmenin anlamı yok."""
    from short_bot.db import mark_bank_topic_used
    eng = _eng(tmp_path)
    _doldur(eng, ["Zaten uretilmis konu", "Aktif konu"])
    rows = all_bank_topics(eng, "k")
    kullanilmis = next(r for r in rows if r["topic"] == "Zaten uretilmis konu")
    mark_bank_topic_used(eng, kullanilmis["id"])

    res = audit_bank(eng, "k", language="tr",
                     llm=_llm([{"index": 0, "solid": False, "reason": "x"}]))
    assert res["checked"] == 1, "yalnız AKTİF konu denetlenmeli"


def test_BOS_banka_LLM_CAGIRMAZ(tmp_path):
    def _patla(*a, **kw):
        raise AssertionError("boş banka için LLM çağrıldı")
    assert audit_bank(_eng(tmp_path), "k", language="tr", llm=_patla) == \
        {"checked": 0, "rejected": 0}


def test_LLM_PATLARSA_hicbir_sey_REDDEDILMEZ(tmp_path):
    """Denetim çökerse SAĞLAM konuları silmektense hiçbir şey yapmamak yeğdir."""
    eng = _eng(tmp_path)
    _doldur(eng, ["Konu bir", "Konu iki"])

    def _patla(*a, **kw):
        raise RuntimeError("sonnet yok")

    res = audit_bank(eng, "k", language="tr", llm=_patla)
    assert res["rejected"] == 0
    assert all(r["status"] == "active" for r in all_bank_topics(eng, "k"))
