import pytest
from short_bot.reel_colors import luminance, contrast_text, ensure_bright


def test_luminance_dark_vs_light():
    assert luminance("#000000") < 0.05
    assert luminance("#ffffff") > 0.95
    assert luminance("#0a2540") < 0.15          # koyu lacivert
    assert luminance("#38bdf8") > 0.4           # açık mavi


def test_contrast_text():
    assert contrast_text("#0a2540") == "#ffffff"   # koyu zemin → beyaz yazı
    assert contrast_text("#ffd400") == "#111111"   # açık zemin → koyu yazı
    assert contrast_text("#38bdf8") == "#111111"


def test_contrast_text_midtone_prefers_dark():
    # Orta-ton accent'ler (kutu zemini) koyu yazıyla daha okunur (WCAG)
    assert contrast_text("#14b8a6") == "#111111"   # teal (lum ~0.37)
    assert contrast_text("#999999") == "#111111"   # gri (lum ~0.32)
    # Gerçekten koyu olanlar hâlâ beyaz
    assert contrast_text("#333333") == "#ffffff"


def test_ensure_bright_lightens_dark_keeps_light():
    out = ensure_bright("#0a2540")
    assert luminance(out) >= 0.5                 # aydınlatıldı
    assert ensure_bright("#38bdf8") == "#38bdf8" # zaten parlak → değişmez


def test_invalid_hex_safe():
    assert contrast_text("garbage") in ("#111111", "#ffffff")
    assert ensure_bright("garbage")              # patlamaz
