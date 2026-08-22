"""Metaforik HOOK, görseli ve vision kapısını zehirlememeli.

GERÇEK HATA (short_id=745, parazit arı & tırtıl):
  anlatım hook'u: "Bir geminin mürettebatı, görünmez bir tehditle çevrili bir
                   fırtınada mahsur kalırsa ne olur?"   (gemi = tırtıl METAFORU)
  ekranda:        Boğaz'da GERÇEK BİR GEMİ — hem açılışta hem kapanışta.
  39 saniyenin ~13'ü alakasız bir öznede geçti.

İKİ KUSUR:
1. Vision kapısına bağlam olarak "konu | HOOK" gönderiliyordu. Hook metaforikse
   içindeki kelime ("gemi") bağlama sızıyor ve kapı gemiyi BAĞLAMDA sayıyor —
   metaforu elemesi gereken mekanizmanın kendisi metaforu MEŞRULAŞTIRIYOR.
2. hook_visual metaforu harfiyen izliyordu. Metafor SÖZDE yaşar; GÖRSEL videonun
   gerçek öznesini göstermeli — insan editör de böyle yapar.
"""
from short_bot.config import ReelConfig
from short_bot.reel_narration import build_reel_prompt


class _Ch:
    language = "tr"
    reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(35, 45))


def test_vision_context_is_the_topic_not_the_metaphorical_hook():
    """Kapıya giden bağlam KONU olmalı — hook'un metaforu değil."""
    import inspect

    import short_bot.reel as reel
    src = inspect.getsource(reel.produce_reel_video)
    ctx_lines = [ln for ln in src.splitlines() if "_video_context =" in ln]
    assert ctx_lines, "_video_context bulunamadı"
    line = ctx_lines[0]
    assert "narration.hook" not in line, (
        "hook bağlama sızıyor: metaforik hook ('gemi'), kapının elemesi gereken "
        "metaforu MEŞRULAŞTIRIR")
    assert "topic" in line


def test_narration_prompt_forbids_metaphorical_hook_visual():
    """hook_visual/close_visual videonun GERÇEK öznesini göstermeli."""
    p = build_reel_prompt("parazit arı tırtılı ele geçiriyor", _Ch())
    low = p.lower()
    # Gemi karşı-örneği prompt'ta AÇIKÇA yasaklanmalı (soyut kural yetmiyor)
    assert "ship" in low, "gemi karşı-örneği prompt'ta yok"
    assert "hook_visual" in p
