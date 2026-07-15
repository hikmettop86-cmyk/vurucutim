"""Testler arası küresel durum yalıtımı."""
import pytest


@pytest.fixture(autouse=True)
def _dil_paketi_yalitimi():
    """Her testten sonra dil paketi küresel durumunu sıfırla.

    `lang_pack._user_dir` bir modül-globali ve `load_pack` lru_cache'li. `create_app`
    onu kullanıcının config dizinine kuruyor; web testleri de create_app çağırıyor.
    Sıfırlanmazsa bir testin tmp_path'i bir sonrakine sızar ve sonuçlar test SIRASINA
    bağlı olur — özellikle "paket YOKSA RuntimeError" testleri sahte başarı verir.
    """
    yield
    from short_bot.lang_pack import set_user_dir
    set_user_dir(None)


@pytest.fixture(autouse=True)
def _olgu_denetimi_kapali(monkeypatch):
    """Anlatım olgu denetimini birim testlerde KAPAT — GERÇEK LLM çağrısı yapıyor.

    `write_reel_narration` artık senaryoyu olgusal doğruluk açısından denetliyor
    (reel_factcheck). Kapı `run_json`u KENDİ modülünden çağırıyor; `reel_narration.
    run_json`u mock'layan testler onu kaçırıyor ve GERÇEK ağ çağrısı yapılıyordu.

    Yakalandığında öğretici bir şey oldu: kapı, bir test fixture'ındaki cümleyi
    ("Kondor gökyüzünün avcısı") gerçekten yanlış buldu — kondor avcı değil, leş
    yiyicidir. Kapı çalışıyor; ama birim testler LLM çağırmamalı (yavaş, ücretli,
    deterministik değil).

    Kapıyı SINAYAN testler (tests/test_reel_factcheck.py) `check_narration`ı kendileri
    monkeypatch'liyor ve bu fixture'ı EZİYOR.
    """
    import short_bot.reel_narration as RN
    monkeypatch.setattr(RN, "check_narration", lambda *a, **kw: [], raising=False)
    # Mizah kapısı da GERÇEK LLM çağırıyor — persona'lı üretim testleri onu kaçırmasın.
    # (test_reel_narration_persona.py kendi monkeypatch'iyle bunu EZER.)
    monkeypatch.setattr(RN, "check_humor", lambda *a, **kw: [], raising=False)
