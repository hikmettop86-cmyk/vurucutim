"""ffprobe ile medya süresi ölçümü + sondaki sessizliğin ölçülmesi."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Konuşma sayılmayacak eşik. -45 dBFS: TTS'in oda tonu/dither zemini bunun altında,
# en kısık fısıltı bile üstünde kalır.
SILENCE_DB = -45
# Bu kadar süren sessizlik "sessizlik" sayılır (nefes ve nokta arası duraklar değil).
SILENCE_MIN_S = 0.6


def probe_duration_s(path: Path, ffprobe_path: str = "ffprobe") -> float:
    """Ses/video dosyasının süresini saniye cinsinden döndürür."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Medya dosyası yok: {p}")
    proc = subprocess.run(
        [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(p)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    raw = (proc.stdout or "").strip()
    try:
        return float(raw)
    except ValueError as e:
        raise RuntimeError(
            f"ffprobe süreyi okuyamadı ({p.name}): {proc.stderr[-300:] or raw!r}"
        ) from e


def trailing_silence_s(path: Path, *, duration_s: float,
                       ffmpeg_path: str = "ffmpeg") -> float:
    """Dosyanın SONUNDAKİ kesintisiz sessizliğin süresi.

    NEDEN: ai33 metnin bir öbeğini okumadan geçtiğinde dosyayı beklenen uzunluğa
    SESSİZLİKLE dolduruyor. Ölçüldü — sağlam seslendirmede sondaki sessizlik
    0.3-0.5sn, öbek düşen ikisinde 3.4sn ve 6.9sn. Yani bu, kaybın whisper'dan
    BAĞIMSIZ işareti: whisper sessizlikte metin uydurabiliyor (ve uydurdu), ama
    sessizliğin kendisi yalan söylemez.

    Ayrıca ölü hava kendi başına kusur: video 7 saniye konuşmasız akarsa izleyici
    bittiğini sanır ve döngü kırılır.
    """
    proc = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-i", str(path),
         "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN_S:g}",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", proc.stderr or "")]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", proc.stderr or "")]
    if not starts:
        return 0.0
    last = starts[-1]
    # Son sessizlik kapandıysa (ardından yine konuşma var) → sonda sessizlik yok.
    if ends and ends[-1] > last:
        return 0.0
    return max(0.0, duration_s - last)
