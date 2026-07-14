"""DOĞRULAMA KAPISI — prompt'a güvenmek YETMİYOR.

ÖLÇÜLDÜ: damıtma prompt'u "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır"
cümlesini YASAK ÖRNEK olarak birebir veriyordu. Model onu kelimesi kelimesine yazdı ve
konu bankasına girdi. İkinci bir göz şart.
"""
from short_bot.topic_propose import Verdict, verify_topics


def _llm(yargilar):
    def _f(prompt, schema, **kw):
        _f.prompt = prompt
        return schema.model_validate({"verdicts": yargilar})
    _f.prompt = ""
    return _f


def test_yargilar_DONER():
    llm = _llm([{"index": 0, "solid": False, "reason": "içi boş"},
                {"index": 1, "solid": True, "reason": ""}])
    out = verify_topics(["a", "b"], language="tr", llm=llm)
    assert [v.solid for v in out] == [False, True]
    assert isinstance(out[0], Verdict)


def test_KURALLAR_PROMPTA_girer():
    llm = _llm([{"index": 0, "solid": True}])
    verify_topics(["x"], language="tr", llm=llm)
    p = llm.prompt
    assert "VAAT" in p
    assert "GENELLEME" in p
    # Ölçülen GERÇEK çöp, prompt'ta örnek olarak veriliyor:
    assert "kusursuz bir uyum" in p
    # Ve bilimsel olarak yanlış olanı da elemeli:
    assert "saniyeler" in p


def test_konular_PROMPTA_numarali_girer():
    llm = _llm([{"index": 0, "solid": True}])
    verify_topics(["Kalp yilda %1 yenilenir"], language="tr", llm=llm)
    assert "0. Kalp yilda %1 yenilenir" in llm.prompt


def test_BOS_liste_LLM_CAGIRMAZ():
    def _patla(*a, **kw):
        raise AssertionError("boş liste için LLM çağrıldı")
    assert verify_topics([], language="tr", llm=_patla) == []


def test_EKSIK_yargi_SAGLAM_SAYILMAZ():
    """Model bazı konulara yargı vermezse onları geçirmek KAPIYI DELMEKTİR —
    çöp konu sessizce içeri girer."""
    llm = _llm([{"index": 0, "solid": True}])          # 1. konu için yargı YOK
    out = verify_topics(["a", "b"], language="tr", llm=llm)
    assert len(out) == 2
    assert out[1].solid is False
    assert "yargı" in out[1].reason.lower()


def test_LLM_PATLARSA_hepsi_SAGLAM_sayilir():
    """Denetim çökerse üretimi DURDURMAYIZ — ama loglanır.

    Alternatif (hepsini elemek) tek bir LLM arızasında bankayı sıfırlardı."""
    def _patla(*a, **kw):
        raise RuntimeError("sonnet yok")
    out = verify_topics(["a", "b"], language="tr", llm=_patla)
    assert all(v.solid for v in out)
    assert all("denetlenemedi" in v.reason for v in out)


def test_LLM_None_ise_hepsi_SAGLAM():
    out = verify_topics(["a"], language="tr", llm=None)
    assert out[0].solid is True
    assert "denetlenemedi" in out[0].reason
