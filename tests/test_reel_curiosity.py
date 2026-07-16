"""Merak mimarisi: 3 aday senaryo -> rubrik yargici -> doktor (spec 2026-07-16)."""
from types import SimpleNamespace


def _kanal():
    reel = SimpleNamespace(target_duration_s=(45, 60), persona="vahsi_mizah",
                           mascot_name="", mascot_animal="", mascot_trait="")
    return SimpleNamespace(reel=reel, language="tr")


def _fake_draft(hook="hook cümlesi burada", oq="Bu tip neden korkutuyor?"):
    from short_bot.reel_models import FDDraftNarration
    return FDDraftNarration.model_validate({
        "hook": hook, "cover_title": "MANŞET",
        "beats": [{"text": "beat sıfır metni burada", "visual_query": "", "keyword": "K0"},
                  {"text": "beat bir metni burada", "visual_query": "", "keyword": "K1"},
                  {"text": "beat iki metni burada", "visual_query": "", "keyword": "K2"}],
        "close": "hook cümlesi kapanış", "mood": "upbeat",
        "open_question": oq, "reveal_beat": 2, "clip_order": [1, 0, 2]})


def test_iskeletler_uc_farkli_strateji():
    from short_bot.reel_curiosity import CURIOSITY_SKELETONS
    assert len(CURIOSITY_SKELETONS) == 3
    etiketler = [e for e, _ in CURIOSITY_SKELETONS]
    assert len(set(etiketler)) == 3
    talimatlar = " ".join(t for _, t in CURIOSITY_SKELETONS)
    # üç strateji: gizem-önce / tırmanan bahis / sahte çözüm+twist
    assert "SONA SAKLA" in talimatlar or "sona sakla" in talimatlar.lower()
    assert "DAHA BÜYÜK" in talimatlar or "daha büyük" in talimatlar.lower()
    assert "TERS KÖŞE" in talimatlar or "twist" in talimatlar.lower()


def test_rubrik_kritik_maddeleri_iceriyor():
    # NOT .lower() ile arama YAPMA: Python'da "AÇIK".lower() == "açik" (ı değil i)
    # — Türkçe kavramları rubrikteki YAZILDIĞI hâliyle ara.
    from short_bot.reel_curiosity import RUBRIC
    for kavram in ("AÇIK DÖNGÜ", "SIZINTI", "KANCASI", "TIRMANIŞ", "ÖDEME",
                   "MİZAH", "GÖRÜNTÜ SADAKATİ", "KLİŞE"):
        assert kavram in RUBRIC, f"rubrikte eksik kavram: {kavram}"
