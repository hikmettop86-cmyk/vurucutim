"""Hedef dil, LLM çıktısının modele girdiği SINIRDA kurulmalı.

Kurulmazsa strip_foreign_diacritics contextvar'ın varsayılanına ("tr") düşer ve Almanca
anlatım sessizce bozulur — düzelttiğimiz hatanın ta kendisi. Task 1 aracı yaptı; bu
testler onun GERÇEKTEN BAĞLANDIĞINI kanıtlıyor.
"""
import inspect

from short_bot.reel_models import ReelBeat
from short_bot.text_normalize import language


def _beat(text):
    return ReelBeat(text=text, visual_query="bier garten", keyword="")


def test_almanca_baglamda_anlatim_METNI_BOZULMAZ():
    """EN AĞIR SESSİZ HATA: 'Täglich' -> 'Taglich'. TTS yanlış okur, altyazı yanlış."""
    with language("de"):
        b = _beat("Täglich frisches Bier aus Bayern")
    assert b.text == "Täglich frisches Bier aus Bayern"


def test_baglam_kurulmazsa_TURKCE_davranis_korunur():
    # Regresyon kalkanı: Türkçe çıktıya sızan yabancı aksan silinmeye devam etmeli.
    b = _beat("CANLÍ yayin burada simdi")
    assert b.text == "CANLI yayin burada simdi"


def test_almanca_baglam_YABANCI_aksani_yine_de_siler():
    # Almanca alfabesinde olmayan aksan (é) yine temizlenir.
    with language("de"):
        b = _beat("Ein Bier im café heute abend")
    assert b.text == "Ein Bier im cafe heute abend"


def test_run_pipeline_kanalin_DILINI_kurar():
    """run_pipeline gövdesi `with language(channel.language)` içinde koşmalı.

    Kaynağı okuyoruz: pipeline'ı gerçekten çalıştırmak ffmpeg/LLM/TTS ister. Aranan
    şey yapısal — dış sarmalayıcı dili kuruyor mu?
    """
    import short_bot.pipeline as P
    kaynak = inspect.getsource(P.run_pipeline)
    assert "language(" in kaynak, "run_pipeline dili KURMUYOR"
    assert "channel.language" in kaynak


def test_run_pipeline_ICERIDE_kosan_kod_dili_GORUR(monkeypatch):
    """Sarmalayıcının gerçekten iş gördüğünü kanıtla: iç fonksiyon çağrıldığı anda
    contextvar Almanca'ya kurulmuş olmalı."""
    import short_bot.pipeline as P
    from short_bot.text_normalize import current_language

    gorulen = {}

    def _sahte_inner(**kw):
        gorulen["lang"] = current_language()
        return "tamam"

    monkeypatch.setattr(P, "_run_pipeline_inner", _sahte_inner)

    class _Ch:
        language = "de"
        slug = "k"

    assert P.run_pipeline(channel=_Ch(), settings=None, db_path=None,
                          music_root=None, templates_dir=None, cache_dir=None,
                          logs_dir=None) == "tamam"
    assert gorulen["lang"] == "de", "pipeline gövdesi Türkçe bağlamda koştu"


def test_pipeline_bittikten_SONRA_dil_sizmaz(monkeypatch):
    import short_bot.pipeline as P
    from short_bot.text_normalize import current_language

    monkeypatch.setattr(P, "_run_pipeline_inner", lambda **kw: None)

    class _Ch:
        language = "de"
        slug = "k"

    P.run_pipeline(channel=_Ch(), settings=None, db_path=None, music_root=None,
                   templates_dir=None, cache_dir=None, logs_dir=None)
    assert current_language() == "tr", "dil bağlamı sızdı"
