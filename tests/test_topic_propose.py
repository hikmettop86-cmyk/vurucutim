"""Damıtma ve üretim TEK prompt.

ÖLÇÜLDÜ: kanıt (outlier videosu) KAYNAK VİDEOYA ait, konu CÜMLESİNE değil. 871 kat
patlamış bir videodan damıtılan cümle içi boş çıkabiliyor:
    "Gerçek bir sinir sistemi, ... karmaşık bir otoyol"          ← hiçbir şey demiyor
Sonnet 5 ise hiçbir YouTube verisi görmeden somut konu yazıyor.

O yüzden kanıt bir ZORUNLULUK değil, İLHAM: "bu başlıklar bu nişte patladı; ilham al
ama kopyalamak zorunda değilsin". Kanıt yoksa saf üretim koşar — BANKA ASLA KURUMAZ ve
referans kanal / YouTube API anahtarı OPSİYONEL olur.
"""
import pytest

from short_bot.topic_propose import ProposedTopic, propose_topics

KANIT = [
    {"source_title": "Kalbin kendi elektrigi", "views": 900_000, "subs": 12_000},
    {"source_title": "Karaciger kendini yeniler", "views": 400_000, "subs": 9_000},
]


def _llm(topics):
    """Sahte Sonnet: verilen konuları döndürür, gördüğü prompt'u kaydeder."""
    def _f(prompt, schema, **kw):
        _f.gorulen = prompt
        return schema.model_validate({"topics": topics})
    _f.gorulen = ""
    return _f


def _k(t, src="", views=0, subs=0):
    return {"topic": t, "source_title": src, "views": views, "subs": subs,
            "hook_pattern": ""}


def test_KANIT_VARSA_kaynak_bilgisi_tasinir():
    llm = _llm([_k("Karacigerin %70'i gitse 3 haftada geri buyur",
                   "Karaciger kendini yeniler", 400_000, 9_000)])
    out = propose_topics("insan vucudu", language="tr", evidence=KANIT,
                         existing=[], count=5, llm=llm)
    assert len(out) == 1
    assert isinstance(out[0], ProposedTopic)
    assert out[0].views == 400_000
    assert out[0].source == "search"          # kanıttan geldi


def test_KANIT_YOKSA_uretim_kosar():
    """BANKA ASLA KURUMAZ. Eskiden taze outlier yoksa ValueError fırlıyordu."""
    llm = _llm([_k("Mide ic zari hucrelerini 3-4 gunde bir yeniler")])
    out = propose_topics("insan vucudu", language="tr", evidence=[],
                         existing=[], count=5, llm=llm)
    assert len(out) == 1
    assert out[0].source == "llm"
    assert out[0].views == 0


def test_KANITSIZ_konu_llm_ETIKETLENIR():
    """Kanıt VARKEN bile model kendi olgusunu yazabilir → o konu 'llm' sayılır."""
    llm = _llm([_k("Kanittan gelen", "Kalbin kendi elektrigi", 900_000, 12_000),
                _k("Modelin kendi bildigi olgu")])
    out = propose_topics("insan vucudu", language="tr", evidence=KANIT,
                         existing=[], count=5, llm=llm)
    kaynak = {t.topic: t.source for t in out}
    assert kaynak["Kanittan gelen"] == "search"
    assert kaynak["Modelin kendi bildigi olgu"] == "llm"


def test_REFERANS_kaniti_reference_etiketlenir():
    ref = [{"source_title": "Ref video", "views": 5, "subs": 1, "ref": True}]
    llm = _llm([_k("Ref konusu", "Ref video", 5, 1)])
    out = propose_topics("x", language="tr", evidence=ref, existing=[],
                         count=5, llm=llm)
    assert out[0].source == "reference"


def test_MEVCUT_konular_PROMPTA_verilir():
    llm = _llm([_k("Yeni konu")])
    propose_topics("x", language="tr", evidence=[],
                   existing=["Zaten bankada olan konu"], count=5, llm=llm)
    assert "Zaten bankada olan konu" in llm.gorulen


def test_KANIT_ILHAM_olarak_sunulur_ZORUNLULUK_degil():
    """Prompt açıkça 'kopyalamak zorunda değilsin' demeli — ölçüldü, zorlama damıtma
    içi boş cümle üretiyor."""
    llm = _llm([_k("x y z")])
    propose_topics("x", language="tr", evidence=KANIT, existing=[], count=5, llm=llm)
    assert "ZORUNDA DEĞİLSİN" in llm.gorulen


def test_OLCULEN_prompt_kurallari_KORUNUR():
    """Bu kurallar GERÇEK HATALARDAN öğrenildi — atılamaz."""
    llm = _llm([_k("x y z")])
    propose_topics("x", language="tr", evidence=[], existing=[], count=5, llm=llm)
    p = llm.gorulen
    assert "SÖZDE-BİLİM" in p          # mistik şifa konusu bankaya girmişti
    assert "VAAT ETME" in p            # "şaşırtıcı rakamlarla ifade edilebilir"
    assert "GENELLEME" in p            # "her organ kusursuz uyum içinde çalışır"
    assert "TARİF ETMEZ" in p          # "…anlatan bir video"
    assert "saniyeler" in p            # muz/sindirim: bilimsel olarak YANLIŞ konu


def test_ADET_SINIRI_uygulanir():
    llm = _llm([_k(f"Konu {i}") for i in range(20)])
    out = propose_topics("x", language="tr", evidence=[], existing=[], count=5,
                         llm=llm)
    assert len(out) == 5


def test_BOS_konu_elenir():
    llm = _llm([_k("   "), _k("Gecerli konu burada")])
    out = propose_topics("x", language="tr", evidence=[], existing=[], count=5,
                         llm=llm)
    assert [t.topic for t in out] == ["Gecerli konu burada"]


def test_META_TARIF_elenir():
    """'…anlatan bir video' bir konu değil, video tarifidir (gerçek üretim hatası)."""
    llm = _llm([_k("Einstein'in beynini konu alan bir inceleme"),
                _k("Einstein'in beyni olumunden sonra izinsiz calindi")])
    out = propose_topics("x", language="tr", evidence=[], existing=[], count=5,
                         llm=llm)
    assert len(out) == 1
    assert "inceleme" not in out[0].topic


def test_LLM_YOKSA_hata():
    """MEKANİK FALLBACK YOK. Eskiden llm_call=None iken ham başlık konu oluyordu —
    ölçülen çöpün kaynaklarından biri o. Konu üretemiyorsak DURMAK yeğdir."""
    with pytest.raises(RuntimeError, match="konu üretilemedi"):
        propose_topics("x", language="tr", evidence=[], existing=[], count=5,
                       llm=None)


def test_KANIT_YOKKEN_kanit_blogu_PROMPTA_GIRMEZ():
    llm = _llm([_k("x y z")])
    propose_topics("x", language="tr", evidence=[], existing=[], count=5, llm=llm)
    assert "KANIT" not in llm.gorulen
