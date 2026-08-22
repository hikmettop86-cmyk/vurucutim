"""SFX ses seviyesi: vurgu olsun, YATAK olmasın.

GERÇEK ŞİKÂYET (arı videosu): "sfx sesleri çok baskın, izleyici rahatsız edebilir".

Ölçüm üç kusur gösterdi:
1. SÜRE: Mixkit "sfx" dosyalarının bir kısmı SFX değil, AMBİYANS YATAĞI —
   technology/1000 = 25.4sn, technology/2507 = 23.5sn. Kesimler ~2.5sn'de bir
   olduğu için 25 saniyelik bir ses AYNI ANDA 10 SFX üst üste binmesine yol
   açıyordu. "Baskın" hissin ana kaynağı buydu.
2. SEVİYE FARKI: dosyalar arasında 20.3 dB fark (cinematic -12.4 dB vs
   click -32.7 dB) → bir vurgu fısıltı, diğeri patlama.
3. GENEL SEVİYE: assembler'da sabit volume=0.6 (anlatım 1.0) → SFX neredeyse
   konuşma kadar yüksek.
"""
import subprocess
from pathlib import Path

import pytest

from short_bot.assets_library import MAX_SFX_S, SFX_TARGET_LUFS, normalize_sfx


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg yok")


def _tone(path: Path, seconds: float, volume: str = "0.5") -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}",
         "-af", f"volume={volume}", str(path)],
        check=True, capture_output=True)
    return path


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return float(out.strip())


def test_long_ambient_bed_is_trimmed_to_an_accent(tmp_path):
    """25 saniyelik 'sfx' kesilmeli — yoksa kesimlerde üst üste biner."""
    src = _tone(tmp_path / "bed.mp3", 25.0)
    assert _duration(src) > 20
    out = normalize_sfx(src)
    assert out is not None
    assert _duration(out) <= MAX_SFX_S + 0.15, (
        f"uzun ambiyans kesilmedi: {_duration(out):.1f}sn")


def test_short_sfx_keeps_its_length(tmp_path):
    """Zaten kısa olan SFX uzatılmaz/kırpılmaz."""
    src = _tone(tmp_path / "hit.mp3", 0.8)
    normalize_sfx(src)
    assert 0.6 <= _duration(src) <= 1.1


def test_loudness_is_equalized_across_files(tmp_path):
    """20 dB'lik seviye uçurumu kapanmalı: sessiz ve gürültülü dosya yakınsasın."""
    quiet = _tone(tmp_path / "quiet.mp3", 1.0, volume="0.02")
    loud = _tone(tmp_path / "loud.mp3", 1.0, volume="1.0")

    def mean_db(p: Path) -> float:
        r = subprocess.run(["ffmpeg", "-i", str(p), "-af", "volumedetect",
                            "-f", "null", "-"], capture_output=True, text=True)
        for line in r.stderr.splitlines():
            if "mean_volume:" in line:
                return float(line.split("mean_volume:")[1].strip().split()[0])
        raise AssertionError("mean_volume okunamadı")

    before = abs(mean_db(quiet) - mean_db(loud))
    assert before > 15, f"test kurulumu zayıf (fark {before:.1f} dB)"

    normalize_sfx(quiet)
    normalize_sfx(loud)
    after = abs(mean_db(quiet) - mean_db(loud))
    assert after < 6.0, (
        f"seviyeler eşitlenmedi: önce {before:.1f} dB → sonra {after:.1f} dB")


def test_normalize_is_idempotent(tmp_path):
    """İki kez normalize etmek dosyayı bozmamalı (kütüphane tekrar taranabilir)."""
    p = _tone(tmp_path / "a.mp3", 3.0)
    normalize_sfx(p)
    d1 = _duration(p)
    normalize_sfx(p)
    assert abs(_duration(p) - d1) < 0.1


def test_broken_file_is_skipped_not_crashing(tmp_path):
    """Bozuk dosya kütüphane kurulumunu DÜŞÜRMEZ (fail-open)."""
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not an mp3")
    assert normalize_sfx(bad) is None
    assert bad.exists()          # dokunulmadı


def test_target_loudness_is_well_below_narration():
    """Hedef seviye anlatımın belirgin ALTINDA olmalı (vurgu, yarış değil)."""
    assert SFX_TARGET_LUFS <= -20, "SFX hedefi konuşmayla yarışacak kadar yüksek"
