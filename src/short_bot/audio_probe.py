"""ffprobe ile medya süresi ölçümü."""
from __future__ import annotations

import subprocess
from pathlib import Path


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
