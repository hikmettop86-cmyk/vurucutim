"""SP3: kürate senaryo yazıcısı + klip-uzunluğundan süre türetme (loop önleme)."""
from types import SimpleNamespace

from short_bot.config import ReelConfig
from short_bot.reel_narration import (_CuratedDraft, curated_target,
                                      write_curated_narration)


def test_curated_target_derives_from_clip_length():
    assert curated_target(6, (30, 45)) == (12, 16)     # kısa → ~klip×2.6 (yavaşlatma kapsar)
    assert curated_target(20, (30, 45)) == (16, 20)    # yeterince uzun → ~klip boyu
    assert curated_target(60, (30, 45)) == (41, 45)    # kanal üstüyle capped
    assert curated_target(0, (30, 45)) == (30, 45)     # okunamadı → kanal hedefi


def test_write_curated_narration_faithful_build(monkeypatch):
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    draft = _CuratedDraft(
        hook="Su tipe bak hele", beats=["Bir kedi burada", "Iki goz kirpar",
                                        "Uc makine saray"],
        close="Kapanis cumlesi", mood="upbeat",
        title="Kedi basligi seo", cover_title="EN RAHAT TIP")
    monkeypatch.setattr("short_bot.reel_narration.run_json", lambda *a, **k: draft)
    n = write_curated_narration("You'll do the laundry later",
                                "A cat resting in a dryer.", channel=ch, subject="cat")
    assert n.hook == "Su tipe bak hele"
    assert len(n.beats) == 3
    assert all(b.visual_query == "cat" for b in n.beats)   # tek hazır klibe sabit
    assert n.title == "Kedi basligi seo"
    assert n.cover_title == "EN RAHAT TIP"


def test_write_curated_narration_single_call_deterministic_budget(monkeypatch):
    # CLI Sonnet ~50sn/çağrı → TEK LLM çağrısı (burst yok, maliyet yok). Taşan senaryo
    # LLM YERİNE deterministik (fit_word_budget) kısaltılır: SONDAN beat atar, MIN_BEATS'e
    # (3) sığdırır. Böylece klip gerilip loop'lamaz ve ekstra çağrı yapılmaz.
    long_beats = ["kelime " * 20 for _ in range(5)]   # 5 taşkın beat
    over = _CuratedDraft(hook="cok uzun bir hook cumlesi buraya", beats=long_beats,
                         close="cok uzun bir kapanis cumlesi", mood="upbeat")
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return over
    monkeypatch.setattr("short_bot.reel_narration.run_json", fake)
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    n = write_curated_narration("t", "d", channel=ch, subject="cat",
                                target_duration_s=(8, 12))
    assert calls["n"] == 1              # TEK çağrı (CLI Sonnet: burst yok, ücret yok)
    assert len(n.beats) == 3           # deterministik kısaltma MIN_BEATS'e indirdi (5→3)


def test_curated_prompt_includes_crowd_comments():
    # Üst Reddit yorumları prompt'a 'WHAT THE CROWD SAYS' bloğu olarak girer (vision'a
    # alternatif olay-bağlamı). Boş yorumda blok YAZILMAZ.
    from short_bot.reel_narration import build_curated_prompt
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    p = build_curated_prompt("t", "d", channel=ch,
                             comments=["he inserted it into the trachea", "poor turtle"])
    assert "ARKA-PLAN BAĞLAMI" in p and "trachea" in p
    # yorumlar bağlam; anlatıma META olarak sokulmaması UYARISI da olmalı
    assert "SOKMA" in p
    assert "ARKA-PLAN BAĞLAMI" not in build_curated_prompt("t", "d", channel=ch,
                                                           comments=[])


def test_strip_bard_removes_ozan_leading_and_trailing():
    from short_bot.reel_narration import _strip_bard
    assert _strip_bard("Ozan der ki; saray dediğin makine içiymiş!") == "Saray dediğin makine içiymiş!"
    assert _strip_bard("Bu rahatlık vergiye tabi olmalı, Ozan yazdı.") == "Bu rahatlık vergiye tabi olmalı."
    assert _strip_bard("Aşık Kedi der ki: sıcak köşeyi bulan kazanır") == "Sıcak köşeyi bulan kazanır."
    assert _strip_bard("Tapu onda. Ozan der ki; krallar beklenir.") == "Tapu onda."   # nokta-sonrası
    # ozan yok → dokunma
    assert _strip_bard("Çamaşır yıkanır, amca uyanmaz.") == "Çamaşır yıkanır, amca uyanmaz."


def test_humor_style_config_round_trips(tmp_path):
    from short_bot.config import ReelConfig
    assert ReelConfig(enabled=False).humor_style == ""      # varsayılan boş
