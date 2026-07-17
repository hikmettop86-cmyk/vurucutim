"""Kürate klip TEMİZLEME (SP4): hafif/kenar watermark/logo/kaynak-etiketini vision ile
tespit edip ffmpeg `delogo` ile siler → yazılı klipler de kullanılabilir (arz büyür).

Kullanıcı 3. sorusu (2026-07-17): "logolu veya üzerinde az kalıntı olanlar için temizleme".
Karar: hafif/kenar logo → delogo (çevreden doldur); ağır KAPLAYAN yazı → temizleme artefakt
bırakır → TEMİZLENMEZ (çağıran reddeder/olduğu gibi kullanır). Öznenin üstündeki yazıya
dokunulmaz.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

# region → (x, y, w, h) normalize (0-1) delogo kutusu. Kenar şeritleri tam-genişlik,
# köşeler ~%35 genişlik × %12 yükseklik (tipik kaynak-etiketi/kullanıcı-adı).
_REGION_BOX = {
    "top-left":     (0.00, 0.00, 0.38, 0.12),
    "top-right":    (0.62, 0.00, 0.38, 0.12),
    "bottom-left":  (0.00, 0.88, 0.38, 0.12),
    "bottom-right": (0.62, 0.88, 0.38, 0.12),
    "top":          (0.00, 0.00, 1.00, 0.12),
    "bottom":       (0.00, 0.86, 1.00, 0.14),
}


class WatermarkDetect(BaseModel):
    """Vision watermark yargısı."""
    present: bool = False
    # köşe/kenar konumu: top-left/top-right/bottom-left/bottom-right/top/bottom/none
    region: str = "none"
    # yazı ana ÖZNEYİ mi kaplıyor (ağır → temizlenemez) yoksa köşe/kenarda mı (hafif)
    covers_subject: bool = False
    note: str = ""


_DETECT_PROMPT = (
    "Bu bir video karesi. Görüntüye SONRADAN BİNDİRİLMİŞ watermark / logo / kaynak-etiketi "
    "/ kullanıcı-adı / altyazı şeridi var mı? (doğal sahne yazısı — tabela, ürün etiketi — "
    "DEĞİL; editörün/platformun eklediği katman).\n"
    "- present: böyle bir katman VAR mı?\n"
    "- region: nerede? top-left / top-right / bottom-left / bottom-right / top / bottom / none\n"
    "- covers_subject: bu katman ana ÖZNENİN ÜSTÜNÜ mü kaplıyor (true=ağır, silinince "
    "artefakt kalır) yoksa köşe/kenarda mı duruyor (false=hafif, silinebilir)?\n"
    'SADECE JSON: {"present": <bool>, "region": "<...>", "covers_subject": <bool>, '
    '"note": "<short English>"}'
)


def _dims(clip, ffmpeg_path: str = "ffmpeg") -> tuple[int, int]:
    """(width, height) — okunamazsa (0, 0)."""
    probe = "ffprobe" if ffmpeg_path in ("ffmpeg", "") else ffmpeg_path.replace("ffmpeg", "ffprobe")
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v", "-show_entries",
             "stream=width,height", "-of", "csv=p=0:s=x", str(clip)],
            capture_output=True, text=True, timeout=20)
        w, h = (out.stdout or "0x0").strip().split("x")[:2]
        return int(w), int(h)
    except Exception:  # noqa: BLE001
        return 0, 0


def detect_watermark(clip, *, vision_call, ffmpeg_path: str = "ffmpeg"):
    """Klibin ORTASINDAN bir kare alıp vision'la watermark tespiti. Döner WatermarkDetect
    ya da None (kare/vision hatası → çağıran temizlemez, fail-open)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _clip_duration_s
    dur = _clip_duration_s(clip, ffmpeg_path)
    t = max(0.5, dur / 2) if dur > 0 else 1.0
    try:
        with tempfile.TemporaryDirectory() as td:
            frame = Path(td) / "wm.jpg"
            subprocess.run([ffmpeg_path, "-v", "error", "-y", "-ss", f"{t:.2f}",
                            "-i", str(clip), "-frames:v", "1", "-vf", "scale=480:-1",
                            str(frame)], capture_output=True, timeout=30)
            if not frame.exists() or frame.stat().st_size == 0:
                return None
            return run_json(_DETECT_PROMPT, WatermarkDetect,
                            claude_path=vision_call.claude_path, model=vision_call.model,
                            backend=vision_call.backend, api_key=vision_call.api_key,
                            image_path=frame, retries=1, timeout_s=45)
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[temizlik]: watermark tespiti hatası ({e})")
        return None


def clean_clip(clip, detection, *, ffmpeg_path: str = "ffmpeg", out_path):
    """Hafif/kenar watermark'ı delogo ile sil. Döner temizlenmiş klip yolu, ya da None
    (temizlenecek şey yok / ağır kaplama / hata → çağıran orijinali kullanır)."""
    if detection is None or not detection.present:
        return None
    if detection.covers_subject:
        log.info("  kürate[temizlik]: yazı özneyi KAPLIYOR → temizlenmez (artefakt riski)")
        return None
    box = _REGION_BOX.get((detection.region or "").lower())
    if box is None:
        return None
    w, h = _dims(clip, ffmpeg_path)
    if w <= 0 or h <= 0:
        return None
    fx, fy, fw, fh = box
    # piksel kutusu; delogo kenara değmemeli (x,y>=1, kutu çerçeve içinde).
    x = max(1, int(fx * w)); y = max(1, int(fy * h))
    bw = int(fw * w); bh = int(fh * h)
    bw = min(bw, w - x - 1); bh = min(bh, h - y - 1)
    if bw < 8 or bh < 8:
        return None
    out_path = Path(out_path)
    try:
        subprocess.run([ffmpeg_path, "-v", "error", "-y", "-i", str(clip),
                        "-vf", f"delogo=x={x}:y={y}:w={bw}:h={bh}",
                        "-an", "-preset", "veryfast", str(out_path)],
                       capture_output=True, timeout=180)
        if out_path.exists() and out_path.stat().st_size > 0:
            log.info(f"  kürate[temizlik]: '{detection.region}' watermark'ı silindi "
                     f"(delogo {bw}x{bh}@{x},{y})")
            return out_path
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[temizlik]: delogo hatası ({e}) → orijinal kullanılıyor")
    return None


def clean_if_needed(clip, *, vision_call, ffmpeg_path: str = "ffmpeg", out_path):
    """Tespit + temizle tek adımda. Watermark yoksa/ağırsa/hatada orijinal klibi döndürür."""
    det = detect_watermark(clip, vision_call=vision_call, ffmpeg_path=ffmpeg_path)
    if det is None or not det.present:
        return clip, det
    cleaned = clean_clip(clip, det, ffmpeg_path=ffmpeg_path, out_path=out_path)
    return (cleaned or clip), det
