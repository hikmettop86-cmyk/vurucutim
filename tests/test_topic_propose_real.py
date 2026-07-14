"""GERÇEK Sonnet 5 ile KALİTE KAPISI (dil paketindeki de_real deseninin aynısı).

Diğer testler sahte `llm` kullanır — onlar AKIŞI kanıtlar, KALİTEYİ değil.
Bu dosya modelin gerçekten iş gördüğünü kanıtlar:
  • ölçülen gerçek çöpü ELİYOR mu?
  • kanıtsız üretimde SAĞLAM konu yazıyor mu? (kullanıcının tezi)

YAVAŞ (~1-2 dk). Kırılırsa PROMPT düzeltilmeli — testi zayıflatarak geçirme.
"""
import pytest

from short_bot.llm_sonnet import sonnet_json
from short_bot.topic_propose import propose_topics, verify_topics


def _sonnet(prompt, schema, **kw):
    return sonnet_json(prompt, schema)


# GERÇEK bankadan alınmış çöp (ölçüldü: vucudun-gizli-onarim-gucu)
COP = [
    "Vücudumuzdaki her organ, hayatta kalmak için kusursuz bir uyum içinde çalışır.",
    "Vücuttaki kemik sayısı şaşırtıcı rakamlarla ifade edilebilir",
    "Vücudunuz, yediğiniz bir muzu sindirim sistemi boyunca saniyeler içinde sindirir",
]
# GERÇEK sağlam konular
SAGLAM = [
    "Bebekler 300 kemikle doğar; yetişkinlikte bu sayı 206'ya iner",
    "Karaciğerinin %70'ini kaybetsen bile 3 haftada kendini yeniden büyütür",
]


@pytest.mark.slow
def test_dogrulama_GERCEK_copu_eler():
    """Prompt'a güvenmek yetmiyordu; kapı gerçekten yakalıyor mu?"""
    y = verify_topics(COP + SAGLAM, language="tr", llm=_sonnet)
    assert len(y) == 5

    cop_yargi = y[:len(COP)]
    saglam_yargi = y[len(COP):]

    gecen_cop = [COP[i] for i, v in enumerate(cop_yargi) if v.solid]
    assert not gecen_cop, f"ÇÖP DOĞRULAMADAN GEÇTİ: {gecen_cop}"

    elenen_saglam = [(SAGLAM[i], v.reason)
                     for i, v in enumerate(saglam_yargi) if not v.solid]
    assert not elenen_saglam, f"SAĞLAM KONU ELENDİ: {elenen_saglam}"


@pytest.mark.slow
def test_KANITSIZ_uretim_SAGLAM_konu_verir():
    """KULLANICININ TEZİ: güçlü model, YouTube kanıtı olmadan da iyi konu bulur.

    Ölçüldü ve doğrulandı — bu test onu regresyona karşı kilitliyor.
    """
    out = propose_topics(
        "insan vucudunun gizli onarim ve yenilenme mekanizmalari",
        language="tr", evidence=[], existing=[], count=8, llm=_sonnet)

    assert len(out) >= 5, f"kanıtsız üretim yalnız {len(out)} konu verdi"
    assert all(t.source == "llm" for t in out)
    assert all(t.views == 0 for t in out), "kanıtsız konu sahte izlenme taşıyor"

    # Üretilenler KENDİ doğrulama kapımızdan geçmeli.
    y = verify_topics([t.topic for t in out], language="tr", llm=_sonnet)
    dusen = [(out[i].topic, v.reason) for i, v in enumerate(y) if not v.solid]
    gecen = len(out) - len(dusen)
    assert gecen >= len(out) * 0.7, (
        f"üretilen konuların yalnız {gecen}/{len(out)}'i doğrulamayı geçti.\n"
        f"Elenenler: {dusen}")
