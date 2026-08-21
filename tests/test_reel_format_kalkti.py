"""Reel bir kanal FORMATI olmaktan çıktı — pipeline'ı duruyor.

AYRIM KRİTİK:
  - Kaldırılan: kanal-formatı YÜZEYİ (reel_new.py, reel_edit.py,
    edit_reel.html.j2, channel_format'ın reel dalı). Canlıda 0 kanal
    kullanıyordu ve `/channels/new-reel` menüden erişilemiyordu bile.
  - Kalan: reel PIPELINE'ı (reel.py, reel_narration.py, reel_assembler.py ve
    ~70 test_reel_*.py). Kürate üretimi onu kullanıyor; `dayidiyorki` montaj
    ayarlarını `cfg.reel` üzerinden okumaya devam ediyor.

Bu dosya ikinci maddeyi koruyor: silme işlemi kürate üretimini bozarsa burada
patlar.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_dayidiyorki_kurate_kalir_ve_montaj_ayarlari_durur():
    """Depodaki gerçek kanal — silme işleminin canlı kurbanı olmadığını gösterir."""
    from short_bot.config import load_channel
    from short_bot.formats import channel_format
    p = Path("config/channels/dayidiyorki.yaml")
    if not p.exists():
        pytest.skip("dayidiyorki bu çalışma kopyasında yok")
    cfg = load_channel(p)
    assert channel_format(cfg) == "curated"
    assert cfg.reel is not None and cfg.reel.enabled       # montaj bloğu duruyor
    assert cfg.reel.highlight_color                         # alan kaybı yok
    assert cfg.reel.target_duration_s[1] > cfg.reel.target_duration_s[0]


def test_reel_pipeline_modulleri_duruyor():
    """Silinen yüzey, pipeline değil."""
    import short_bot.reel  # noqa: F401
    import short_bot.reel_narration  # noqa: F401
    from short_bot.config import ReelConfig
    assert ReelConfig(enabled=True, voice_id="v").enabled is True


def test_reel_format_yuzeyi_kalkti():
    from short_bot.formats import FORMATS
    assert "reel" not in FORMATS
    with pytest.raises(ImportError):
        import short_bot.web.routes.reel_edit  # noqa: F401
    with pytest.raises(ImportError):
        import short_bot.web.routes.reel_new  # noqa: F401


def test_reel_bloklu_kanal_kart_formatina_duser():
    """`reel.enabled` artık formatı BELİRLEMEZ. Kürate olmayan bir kanalda o
    blok yalnız montaj ayarı taşır; format sesli/kart kurallarına göre çıkar."""
    from short_bot.config import ChannelConfig, ReelConfig, VoiceConfig
    from short_bot.formats import channel_format
    base = dict(slug="x", name="X", keywords=["k"],
                rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 * * * *",
                duration_s=6, min_score=6.0, max_candidates_per_run=5,
                template="flas", colors={"primary": "#d0021b", "accent": "#ffe600",
                                         "bg_gradient": ["#3a3a3a", "#141414"]},
                handle="@x", output_dir="out", enabled=True, language="tr")
    reel = ReelConfig(enabled=True, voice_id="v")
    assert channel_format(ChannelConfig(**base, reel=reel)) == "card"
    assert channel_format(ChannelConfig(**base, reel=reel,
                                        voice=VoiceConfig(enabled=True, voice_id="v"))) == "voiced"
    assert channel_format(ChannelConfig(**base, reel=reel,
                                        content_source="curated")) == "curated"
