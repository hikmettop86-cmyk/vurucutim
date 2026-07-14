"""Hedef dilde konuşan ANLATICI sesi seç.

ÖLÇÜLDÜ (ai33 /v3/voices, 5 sayfa): 605 ses.
    en=365  hi=38  es=34  vi=22  pt=20  de=18  ko=15  fr=15  ja=12  it=10  tr=8

İki şey kritik:
  • SAYFALAMA ŞART. Varsayılan sayfa çoğunlukla İngilizce; Almanca sesler ileriki
    sayfalarda. İlk sayfada durursan "Almanca ses yok" dersin — ama var.
  • SEÇİM ÖNEMSİZ DEĞİL. Almanca seslerden biri "Mark - Sales Executive", biri
    "Daniel - Teacher, explainer-in-chief". Faceless ilginç-bilgi kanalına ikincisi
    uyar; "ilk erkek sesi al" kuralı bunu bilemez.
"""
import pytest

from short_bot.voice_picker import VoiceChoice, pick_voice, voices_for

DE = [
    {"voice_id": "elevenlabs_a", "name": "Mark - Sales Executive",
     "description": "Energetic sales pitch voice", "language": "de",
     "gender": "male", "accent": "german"},
    {"voice_id": "elevenlabs_b", "name": "Daniel - Teacher, explainer-in-chief",
     "description": "Calm narrator, explains complex topics clearly", "language": "de",
     "gender": "male", "accent": "german"},
]
EN = [{"voice_id": "elevenlabs_x", "name": "Bella", "description": "warm",
       "language": "en", "gender": "female", "accent": "american"}]


def _sayfali(sayfalar):
    """Sahte ai33 list_voices: sayfa sayfa döndürür, sonra boş."""
    def _f(*, api_key, provider="elevenlabs", search="", page=1, page_size=100,
           session=None, **kw):
        return sayfalar[page - 1] if page <= len(sayfalar) else []
    return _f


# --- LİSTELEME -------------------------------------------------------------

def test_HEDEF_DILDEKI_sesler_doner(monkeypatch):
    import short_bot.voice_picker as VP
    monkeypatch.setattr(VP, "list_voices", _sayfali([EN + DE]))
    out = voices_for("de", api_key="K")
    assert [v["voice_id"] for v in out] == ["elevenlabs_a", "elevenlabs_b"]


def test_SAYFALAMA_ilk_sayfada_DURMAZ(monkeypatch):
    """GERÇEK TUZAK: 605 ses var ve ilk sayfa çoğunlukla İngilizce. İlk sayfada
    durursan 'Almanca ses yok' dersin — ama var."""
    import short_bot.voice_picker as VP
    monkeypatch.setattr(VP, "list_voices", _sayfali([EN, EN, DE]))
    out = voices_for("de", api_key="K")
    assert len(out) == 2, "sayfalama yapılmadı → Almanca sesler kaçtı"


def test_SES_YOKSA_hata_INGILIZCEYE_DUSMEZ(monkeypatch):
    """SESSİZ BOZULMA YASAĞI: Almanca kanal İngiliz aksanıyla okur ve bunu HİÇBİR ŞEY
    söylemez. Kanalı bozuk kurmaktansa kurmamak yeğdir."""
    import short_bot.voice_picker as VP
    monkeypatch.setattr(VP, "list_voices", _sayfali([EN]))
    with pytest.raises(RuntimeError, match="ses"):
        voices_for("de", api_key="K")


def test_API_ANAHTARI_YOKSA_hata():
    with pytest.raises(RuntimeError, match="ai33"):
        voices_for("de", api_key="")


# --- SEÇİM -----------------------------------------------------------------

def _llm(voice_id, reason="anlatıcı tonu"):
    def _f(prompt, schema, **kw):
        _f.prompt = prompt
        return schema.model_validate({"voice_id": voice_id, "reason": reason})
    _f.prompt = ""
    return _f


def test_LLM_nise_uygun_ANLATICIYI_secer():
    llm = _llm("elevenlabs_b", "açıklayıcı anlatıcı, bilgi formatına uyar")
    c = pick_voice("de", "bira bahçesi kültürü", voices=DE, llm=llm)
    assert isinstance(c, VoiceChoice)
    assert c.voice_id == "elevenlabs_b"
    assert c.name.startswith("Daniel")
    assert "anlatıcı" in c.reason


def test_ses_ACIKLAMALARI_PROMPTA_girer():
    """Model 'Sales Executive' ile 'Teacher'ı ayırt edebilmeli."""
    llm = _llm("elevenlabs_b")
    pick_voice("de", "bira", voices=DE, llm=llm)
    p = llm.prompt
    assert "Sales Executive" in p and "Teacher" in p
    assert "ANLATICI" in p          # ne aradığımızı açıkça söylüyoruz


def test_LLM_YOKSA_ilk_ses_DURUST_gerekce():
    """Ses seçimi kanalı BOZMAZ, yalnız iyileştirir — burada durmaya gerek yok."""
    c = pick_voice("de", "bira", voices=DE, llm=None)
    assert c.voice_id == "elevenlabs_a"
    assert "seçemedi" in c.reason


def test_LLM_UYDURMA_id_verirse_ilk_ses():
    """Model listede olmayan bir voice_id uydurabilir — kabul etmeyiz."""
    c = pick_voice("de", "bira", voices=DE, llm=_llm("elevenlabs_UYDURMA"))
    assert c.voice_id == "elevenlabs_a"
    assert "listede yok" in c.reason


def test_LLM_PATLARSA_ilk_ses():
    def _patla(*a, **kw):
        raise RuntimeError("sonnet yok")
    c = pick_voice("de", "bira", voices=DE, llm=_patla)
    assert c.voice_id == "elevenlabs_a"


def test_BOS_ses_listesi_hata():
    with pytest.raises(RuntimeError):
        pick_voice("de", "bira", voices=[], llm=None)
