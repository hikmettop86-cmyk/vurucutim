"""Görüntü-öncelikli senaryo modu: senaryo eldeki footage'a UYAR (vision-ses garanti)."""
from types import SimpleNamespace

import short_bot.reel_narration as RN
from short_bot.reel_models import ReelBeat, ReelNarration


def _kanal(persona=""):
    reel = SimpleNamespace(target_duration_s=(45, 60), persona=persona,
                           mascot_name="", mascot_animal="", mascot_trait="")
    return SimpleNamespace(reel=reel, language="tr")


def _fake_narration():
    return ReelNarration(
        hook="hook cümlesi", cover_title="MANŞET",
        beats=[ReelBeat(text="beat sıfır metni burada", visual_query="LLM-uydurdu-0", keyword="K0"),
               ReelBeat(text="beat bir metni burada", visual_query="LLM-uydurdu-1", keyword="K1"),
               ReelBeat(text="beat iki metni burada", visual_query="LLM-uydurdu-2", keyword="K2")],
        close="hook cümlesi kapanış", mood="upbeat")


def test_visual_query_gercek_footage_sorgusuna_sabitlenir(monkeypatch):
    # LLM'in visual_query'leri YOK SAYILIR; beat i = footage sorgusu i (eşleme garanti).
    monkeypatch.setattr(RN, "run_json", lambda *a, **k: _fake_narration())
    n = RN.write_footage_driven_narration(
        "şempanze", ["chimp eating", "chimp screaming", "chimp walking"],
        ["chimpanzee eating", "chimpanzee screaming", "chimpanzee walking"],
        channel=_kanal())
    assert [b.visual_query for b in n.beats] == \
        ["chimpanzee eating", "chimpanzee screaming", "chimpanzee walking"]
    assert n.hook_visual == "chimpanzee eating"       # hook = ilk footage
    assert n.close_visual == "chimpanzee walking"     # close = son footage
    assert [b.text for b in n.beats] == \
        ["beat sıfır metni burada", "beat bir metni burada", "beat iki metni burada"]


def test_prompt_footage_tariflerini_iceriyor(monkeypatch):
    yakalanan = {}
    def fake(prompt, schema, **k):
        yakalanan["prompt"] = prompt
        return _fake_narration()
    monkeypatch.setattr(RN, "run_json", fake)
    RN.write_footage_driven_narration(
        "kartal", ["eagle soaring", "eagle diving", "eagle landing"],
        ["q0", "q1", "q2"], channel=_kanal())
    p = yakalanan["prompt"]
    assert "eagle soaring" in p and "eagle diving" in p   # tarifler prompt'ta
    assert "MATCH THE REAL FOOTAGE" in p                  # görüntü-öncelikli talimat


def test_persona_footage_driven_prompta_girer(monkeypatch):
    yakalanan = {}
    def fake(p, s, **k):
        yakalanan["p"] = p
        return _fake_narration()
    monkeypatch.setattr(RN, "run_json", fake)
    RN.write_footage_driven_narration("karga", ["crow a", "crow b", "crow c"],
                                      ["q0", "q1", "q2"], channel=_kanal("vahsi_mizah"))
    assert "SAHNE MODU" in yakalanan["p"] or "PERSONA" in yakalanan["p"]


def test_footage_yoksa_hata():
    import pytest
    with pytest.raises(ValueError, match="footage tarifi yok"):
        RN.write_footage_driven_narration("x", [], [], channel=_kanal())


def test_prompt_bos_tarif_isaretlenir_ve_olay_yasagi(monkeypatch):
    # Vision tarifi BOŞ klip → prompt LLM'e açıkça 'tarif yok, uydurma' der; yoksa o
    # beat konudan spesifik olay uydurur (gerçek üretim hatası: 'balık' beat'i bir
    # kaplumbağa klibinin üstüne düştü). Ayrıca klip-dışı OLAY anlatımı yasak.
    yakalanan = {}
    monkeypatch.setattr(RN, "run_json",
                        lambda p, s, **k: (yakalanan.__setitem__("p", p),
                                           _fake_narration())[1])
    RN.write_footage_driven_narration(
        "kartal", ["eagle soaring", "", "eagle landing"],   # ortadaki tarif BOŞ
        ["q0", "q1", "q2"], channel=_kanal())
    p = yakalanan["p"]
    assert "no description available" in p          # boş tarif açıkça işaretli
    assert "invent NO specific" in p                # uydurma yasağı
    assert "Do NOT narrate an ACTION or EVENT" in p # klip-dışı olay anlatımı yasak
    assert "must be ABOUT the creature/subject in CLIP" in p  # beat i = klip i öznesi


def test_bos_visual_query_fd_modda_uretimi_dusurmez(monkeypatch):
    # GERÇEK HATA (çeşitleme reçetesi sonrası koşu): model 3 denemede de visual_query
    # alanlarını BOŞ döndürdü → ReelBeat(min_length=2) doğrulaması üretimi düşürdü.
    # Oysa görüntü-önce modda bu alanlar zaten YOK SAYILIP gerçek footage sorgularına
    # sabitleniyor — hiç gerekmeyen alan için üretim düşürülemez. FD ayrıştırma şeması
    # boş visual_query kabul etmeli; sabitleme sonrası sonuç yine dolu olmalı.
    from short_bot.reel_models import FDDraftNarration
    yakalanan = {}

    def fake(prompt, schema, **k):
        yakalanan["schema"] = schema
        # Modelin gerçek hatalı çıktısı: visual_query'ler boş — şema bunu KABUL etmeli
        return schema.model_validate({
            "hook": "hook cümlesi burada", "cover_title": "MANŞET",
            "beats": [{"text": "beat sıfır metni burada", "visual_query": "", "keyword": "K0"},
                      {"text": "beat bir metni burada", "visual_query": "", "keyword": "K1"},
                      {"text": "beat iki metni burada", "visual_query": "", "keyword": "K2"}],
            "close": "hook cümlesi kapanış", "mood": "upbeat"})

    monkeypatch.setattr(RN, "run_json", fake)
    n = RN.write_footage_driven_narration(
        "şempanze", ["chimp a", "chimp b", "chimp c"],
        ["chimpanzee eating", "chimpanzee running", "chimpanzee walking"],
        channel=_kanal())
    assert yakalanan["schema"] is FDDraftNarration        # gevşek FD şeması kullanılıyor
    assert [b.visual_query for b in n.beats] == \
        ["chimpanzee eating", "chimpanzee running", "chimpanzee walking"]  # sabitlendi
    # Dönen nihai nesne yine KATI ReelNarration (script-first güvencesi bozulmaz)
    from short_bot.reel_models import ReelNarration
    assert type(n) is ReelNarration


def test_prompt_seo_title_ister(monkeypatch):
    # Görüntü-önce prompt kısa SEO başlığı (title) istemeli — dosya adı + YouTube
    # başlığı bundan gelir (uzun konu cümlesi yerine).
    yakalanan = {}
    monkeypatch.setattr(RN, "run_json",
                        lambda p, s, **k: (yakalanan.__setitem__("p", p),
                                           _fake_narration())[1])
    RN.write_footage_driven_narration("kartal", ["a", "b", "c"],
                                      ["q0", "q1", "q2"], channel=_kanal())
    p = yakalanan["p"]
    assert '"title"' in p and "SEO" in p


def test_fd_prompt_sert_kelime_butcesi_icerir():
    # Keçi videosu 65.6sn çıktı (hedef 45-60): FD prompt'ta kelime bütçesi YOKTU.
    # Artık reel_word_budget'tan gelen sert sınır prompt'ta.
    from short_bot.reel_narration import build_footage_driven_prompt, reel_word_budget
    ch = _kanal()
    ch.reel.target_duration_s = (30, 45)
    p = build_footage_driven_prompt("kartal", ["a", "b", "c"], channel=ch)
    lo_w, hi_w = reel_word_budget((30, 45))
    assert f"{lo_w}" in p and f"{hi_w}" in p
    assert "WORD BUDGET" in p


def _uzun_taslak(n_beats=3, kelime_per_beat=45):
    from short_bot.reel_models import FDDraftNarration
    beat = " ".join(["kelime"] * kelime_per_beat)
    return FDDraftNarration.model_validate({
        "hook": "hook cümlesi burada uzun uzun anlatıyor",
        "beats": [{"text": beat, "visual_query": "", "keyword": f"K{i}"}
                  for i in range(n_beats)],
        "close": "kapanış cümlesi burada", "mood": "upbeat"})


def test_fd_butce_zorlamasi_asimda_kisaltir():
    # Aslan videosu 143 kelime yazdı (bütçe 54-81) → prompt tek başına yetmiyor.
    # Aşımda TEK kısaltma turu; beat sayısı korunur (klip bağı).
    from short_bot.reel_narration import _fd_enforce_budget
    ch = _kanal(); ch.reel.target_duration_s = (30, 45)
    uzun = _uzun_taslak()
    kisa = _uzun_taslak(kelime_per_beat=20)
    yakalanan = {}

    def inv(p, s):
        yakalanan["p"] = p
        return kisa

    out = _fd_enforce_budget(uzun, ch, "aslan", invoke=inv)
    assert out is kisa
    assert "KISALT" in yakalanan["p"]
    assert "81" in yakalanan["p"]          # üst sınır promptta


def test_fd_butce_icindeyse_dokunmaz():
    from short_bot.reel_narration import _fd_enforce_budget
    ch = _kanal(); ch.reel.target_duration_s = (30, 45)
    kisa = _uzun_taslak(kelime_per_beat=20)   # ~70 kelime, bütçede
    out = _fd_enforce_budget(kisa, ch, "aslan",
                             invoke=lambda p, s: (_ for _ in ()).throw(
                                 AssertionError("bütçedeyken çağrılmamalı")))
    assert out is kisa


def test_fd_butce_beat_sayisi_degisirse_orijinal_kalir():
    from short_bot.reel_narration import _fd_enforce_budget
    ch = _kanal(); ch.reel.target_duration_s = (30, 45)
    uzun = _uzun_taslak(n_beats=3)
    bozuk = _uzun_taslak(n_beats=4, kelime_per_beat=15)
    out = _fd_enforce_budget(uzun, ch, "aslan", invoke=lambda p, s: bozuk)
    assert out is uzun                     # klip bağı bozulamaz


def test_fd_tek_cagri_yolu_butceyi_zorlar(monkeypatch):
    # write_footage_driven_narration da aşımda kısaltma turu yapmalı.
    promptlar = []

    def fake(p, s, **k):
        promptlar.append(p)
        return _uzun_taslak() if len(promptlar) == 1 else _uzun_taslak(kelime_per_beat=20)

    monkeypatch.setattr(RN, "run_json", fake)
    ch = _kanal(); ch.reel.target_duration_s = (30, 45)
    n = RN.write_footage_driven_narration(
        "aslan", ["a", "b", "c"], ["q0", "q1", "q2"], channel=ch)
    assert len(promptlar) == 2
    assert "KISALT" in promptlar[1]
    assert n.word_count() < 90
