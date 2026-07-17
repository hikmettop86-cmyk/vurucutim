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


def test_write_curated_narration_enforces_budget(monkeypatch):
    # Taşan senaryo → kısaltma turu tetiklenir (klip gerilip loop'lamasın).
    long_beats = ["kelime " * 20, "kelime " * 20, "kelime " * 20]
    over = _CuratedDraft(hook="cok uzun bir hook cumlesi buraya", beats=long_beats,
                         close="cok uzun bir kapanis cumlesi", mood="upbeat")
    short = _CuratedDraft(hook="Kisa hook", close="Kisa kapanis", mood="upbeat",
                          beats=["Bir kisacik", "Iki kisacik", "Uc kisacik"])
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return over if calls["n"] == 1 else short   # ilk taslak taşkın, sonra kısa
    monkeypatch.setattr("short_bot.reel_narration.run_json", fake)
    ch = SimpleNamespace(language="tr",
                         reel=ReelConfig(enabled=True, voice_id="v", persona=""))
    n = write_curated_narration("t", "d", channel=ch, subject="cat",
                                target_duration_s=(8, 12))
    assert calls["n"] >= 2                    # kısaltma turu çağrıldı
    assert n.beats[0].text == "Bir kisacik"   # kısaltılmış sürüm kullanıldı
