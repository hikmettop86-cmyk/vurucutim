"""Master renk grade: 12 alakasız stok klibi TEK BİR FİLM gibi okut.

EN GÖRÜNÜR OTOMASYON PARMAK İZİMİZ BU. Pexels/Pixabay/Storyblocks'tan gelen klipler
farklı renk sıcaklığı, pozlama ve kontrasta sahip. Klipten klibe renk ZIPLAMASI,
"bunu bir script birleştirdi" diye bağırır — ve şu an hiçbir renk işlemimiz yok.

İKİ AŞAMA (sıra ÖNEMLİ):
  1. NORMALİZE: her klibin parlaklığını ortak bir hedefe yaklaştır. ÖNCE bu olmalı;
     yoksa ortak grade, uyumsuzluğu BÜYÜTÜR.
  2. LOOK: hepsine AYNI grade + vignette + grain. Tutarlılık > zekâ: video başına
     TEK grade, klip başına değil.
"""
import subprocess

import pytest

from short_bot.reel_grade import (GRADE_TARGET_LUMA, MAX_BRIGHTNESS_DELTA,
                                  grade_vf, luma_delta, measure_luma)


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg yok")


def _clip(path, color, seconds=1.0):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"color=c={color}:s=320x240:d={seconds}",
                    "-r", "25", str(path)], check=True)
    return path


def test_measures_clip_brightness(tmp_path):
    dark = measure_luma(_clip(tmp_path / "d.mp4", "black"))
    bright = measure_luma(_clip(tmp_path / "b.mp4", "white"))
    assert 0.0 <= dark < 0.15
    assert 0.85 < bright <= 1.0


def test_dark_and_bright_clips_are_pulled_toward_each_other(tmp_path):
    """Uyumsuz iki klip ORTAK hedefe çekilmeli — renk zıplaması budur."""
    dark = measure_luma(_clip(tmp_path / "d.mp4", "0x333333"))
    bright = measure_luma(_clip(tmp_path / "b.mp4", "0xCCCCCC"))
    d_dark = luma_delta(dark)
    d_bright = luma_delta(bright)
    assert d_dark > 0, "karanlık klip açılmalı"
    assert d_bright < 0, "parlak klip kısılmalı"
    # Düzeltmeden SONRA aralarındaki fark KAPANMALI
    before = abs(dark - bright)
    after = abs((dark + d_dark) - (bright + d_bright))
    assert after < before


def test_correction_is_clamped_so_a_deliberately_dark_shot_survives():
    """Kasten karanlık bir sahne (siyah zeminde parlayan mikroplar) DÜZLEŞTİRİLMEZ."""
    d = luma_delta(0.02)                       # neredeyse siyah
    assert d <= MAX_BRIGHTNESS_DELTA
    assert abs(luma_delta(GRADE_TARGET_LUMA)) < 1e-9   # hedefteyse dokunma


def test_grade_chain_has_the_cinematic_ingredients():
    vf = grade_vf(0.0)
    assert "eq=" in vf                    # kontrast/doygunluk
    assert "curves=" in vf                # siyahlar kaldırılmış (crushed DEĞİL)
    assert "vignette" in vf
    assert "noise=" in vf                 # grain
    assert "colorbalance" in vf           # tutarlı sıcaklık


def test_brightness_delta_lands_in_the_chain():
    vf = grade_vf(0.07)
    assert "brightness=0.07" in vf


def test_grade_really_changes_the_image(tmp_path):
    """Grade uygulanınca kare GERÇEKTEN değişmeli (filtre sessizce düşmesin)."""
    src = _clip(tmp_path / "s.mp4", "0x808080")
    out = tmp_path / "g.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                    "-vf", grade_vf(luma_delta(measure_luma(src))),
                    "-c:v", "libx264", "-crf", "18", str(out)], check=True)
    assert out.exists() and out.stat().st_size > 0
    assert abs(measure_luma(out) - measure_luma(src)) > 0.005


# --- KARANLIK KLİP KURTARMA ------------------------------------------------
# ÖLÇÜLDÜ (Almanca kanal, short 795 — kare kare incelendi): videonun %29'u YAVG<40
# (0.16) idi, TEPE NOKTASI dahil. Videonun en kritik anında ekran karanlıktı.
# ±0.12'lik sınır 0.11'lik bir klibi ancak 0.23'e çıkarabiliyordu — hâlâ karanlık.

def test_KOTU_POZLANMIS_klip_kurtarilir():
    """Karanlık VE tepesi de sönük → hiçbir şey parlak değil → kötü pozlanmış."""
    from short_bot.reel_grade import (MAX_BRIGHTNESS_DELTA, MAX_RESCUE_DELTA,
                                      luma_delta)
    d = luma_delta(0.11, peak=0.45)          # gerçek ölçüm: YAVG 29 ≈ 0.11
    assert d > MAX_BRIGHTNESS_DELTA, "karanlık klip normal sınırla kısıldı"
    assert d <= MAX_RESCUE_DELTA
    assert 0.11 + d >= 0.35, "kurtarma yetersiz — klip hâlâ karanlık kalır"


def test_SIYAH_ZEMINDE_PARLAYAN_OZNE_kurtarilmaz():
    """'Siyah zeminde parlayan mikroplar': karanlık AMA tepesi parlak → KASITLI.
    Kaldırmak siyah zemini gri bulamaca çevirir."""
    from short_bot.reel_grade import MAX_BRIGHTNESS_DELTA, luma_delta
    d = luma_delta(0.02, peak=0.98)
    assert d == MAX_BRIGHTNESS_DELTA, "sanatsal karanlık bozuldu"


def test_TEPE_bilinmiyorsa_KURTARMA_YOK():
    """Emin olmadığımız klibi zorlamayız."""
    from short_bot.reel_grade import MAX_BRIGHTNESS_DELTA, luma_delta
    assert luma_delta(0.11) == MAX_BRIGHTNESS_DELTA


def test_NORMAL_klip_ESKI_sinirda_kalir():
    from short_bot.reel_grade import DARK_FLOOR, MAX_BRIGHTNESS_DELTA, luma_delta
    d = luma_delta(0.30, peak=0.50)          # eşiğin ÜSTÜNDE
    assert d == MAX_BRIGHTNESS_DELTA
    assert 0.30 > DARK_FLOOR


def test_esik_SINIRINDA_davranis():
    from short_bot.reel_grade import (DARK_FLOOR, MAX_BRIGHTNESS_DELTA,
                                      GRADE_TARGET_LUMA, luma_delta)
    assert luma_delta(DARK_FLOOR, peak=0.4) == MAX_BRIGHTNESS_DELTA   # eşik = normal
    alt = luma_delta(DARK_FLOOR - 0.01, peak=0.4)
    assert alt > MAX_BRIGHTNESS_DELTA                                  # altı = kurtarma
    assert alt == GRADE_TARGET_LUMA - (DARK_FLOOR - 0.01)              # gereken kadar


def test_PARLAK_klip_KISILIR_normal_sinirla():
    """Aşırı parlak klip DE normalize edilir ama kurtarma kuralı onu kapsamaz."""
    from short_bot.reel_grade import MAX_BRIGHTNESS_DELTA, luma_delta
    assert luma_delta(0.90, peak=1.0) == -MAX_BRIGHTNESS_DELTA


def test_luma_KLIBIN_TAMAMINDAN_orneklenir():
    """Eskiden yalnız İLK 12 KARE ölçülüyordu (30fps'de 0,4 sn). Karanlıktan açılan
    bir klip 'zifiri siyah' ölçülüyordu."""
    import inspect

    from short_bot.reel_grade import measure_levels
    src = inspect.getsource(measure_levels)
    assert "fps=2" in src, "klip boyunca örneklenmiyor"
    assert "frames:v" in src and '"30"' in src
    assert "YMAX" in src, "tepe parlaklık ölçülmüyor"
