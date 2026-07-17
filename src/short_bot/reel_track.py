"""Marker özne-TAKİBİ: hareketli özneyi cv2 ile kare-kare izleyip marker'a konum track'i
ekler → ok/işaretçi sabit kalmaz, özneyi takip eder.

GERÇEK SORUN (short 920): marker segment başına TEK subject_x'e (vision tek kareden)
çiziliyordu; özne hareket edince (kaplumbağa/hayvan yürür) ok yerinde donup YANLIŞ yeri
gösteriyordu (kullanıcı: 'oklar hareketli kliplerde de düzgün göstersin').

Çözüm: locate_subject'in bulduğu başlangıç (x,y)'den bir cv2 tracker (CSRT) başlat, alt-
kesimin gösterildiği klip aralığında kareleri izleyip özneyi TAKİP et → [(t, x, y), ...]
track. Overlay __seek bu track'i kare-kare interpole eder. Ekstra VISION çağrısı YOK.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def _new_tracker(cv2):
    """En iyi mevcut cv2 tracker'ı (CSRT tercih, KCF yedek). Yoksa None."""
    for path in ("legacy.TrackerCSRT_create", "TrackerCSRT_create",
                 "legacy.TrackerKCF_create", "TrackerKCF_create"):
        try:
            obj = cv2
            for part in path.split("."):
                obj = getattr(obj, part)
            return obj()
        except Exception:  # noqa: BLE001
            continue
    return None


def track_subject(clip, start_s: float, dur_s: float, x0: float, y0: float, *,
                  ffmpeg_path: str = "ffmpeg", samples: int = 12):
    """Özneyi (x0,y0 normalize başlangıç) [start_s, start_s+dur_s] boyunca cv2 ile takip et.

    Dönüş: [[frac, x, y], ...] (frac 0..1 alt-kesim içinde, x/y normalize) ya da None
    (cv2 yok / kare çıkmadı / hata → çağıran statik konuma düşer, fail-open)."""
    try:
        import cv2
    except Exception:  # noqa: BLE001 — opencv yoksa takip yok, statik marker
        return None
    if dur_s <= 0.35:
        return None
    fps = max(4.0, min(12.0, samples / dur_s))
    try:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(
                [ffmpeg_path, "-v", "error", "-y", "-ss", f"{start_s:.3f}",
                 "-t", f"{dur_s:.3f}", "-i", str(clip),
                 "-vf", f"fps={fps:.2f},scale=480:-2", str(Path(td) / "t%03d.jpg")],
                capture_output=True, timeout=60)
            frames = sorted(Path(td).glob("*.jpg"))
            if len(frames) < 3:
                return None
            f0 = cv2.imread(str(frames[0]))
            if f0 is None:
                return None
            h, w = f0.shape[:2]
            bw, bh = max(24, int(0.22 * w)), max(24, int(0.22 * h))
            bx = max(0, min(w - bw, int(x0 * w - bw / 2)))
            by = max(0, min(h - bh, int(y0 * h - bh / 2)))
            trk = _new_tracker(cv2)
            if trk is None:
                return None
            trk.init(f0, (bx, by, bw, bh))
            n = len(frames)
            out = [[0.0, round(x0, 4), round(y0, 4)]]
            lx, ly = x0, y0
            for k in range(1, n):
                fr = cv2.imread(str(frames[k]))
                if fr is not None:
                    ok, box = trk.update(fr)
                    if ok:
                        lx = min(1.0, max(0.0, (box[0] + box[2] / 2) / w))
                        ly = min(1.0, max(0.0, (box[1] + box[3] / 2) / h))
                out.append([round(k / (n - 1), 3), round(lx, 4), round(ly, 4)])
            return out
    except Exception as e:  # noqa: BLE001 — takip üretimi düşürmesin
        log.info(f"  reel[track]: özne takibi hatası ({e})")
        return None


def attach_marker_tracks(markers, subcuts, clip_paths, clip_starts, *,
                         ffmpeg_path: str = "ffmpeg") -> None:
    """Her marker'ı üreten alt-kesime eşle → özne-takip track'i hesapla → marker['track']
    (YERİNDE). Track [[t_abs, x, y], ...] (timeline saniyesi). Eşleşmez/başarısız → statik."""
    if not markers:
        return
    tracked = 0
    for m in markers:
        i = next((j for j, (si, a, _b) in enumerate(subcuts)
                  if si == m.get("seg") and abs(a - m.get("t0", -9)) < 1e-2), None)
        if i is None or i >= len(clip_paths):
            continue
        dur = float(m["t1"] - m["t0"])
        start = float(clip_starts[i]) if i < len(clip_starts) else 0.0
        trk = track_subject(clip_paths[i], start, dur, float(m["x"]), float(m["y"]),
                            ffmpeg_path=ffmpeg_path)
        if trk and len(trk) >= 3:
            t0 = float(m["t0"])
            m["track"] = [[round(t0 + f * dur, 3), x, y] for f, x, y in trk]
            tracked += 1
    if tracked:
        log.info(f"  reel[track]: {tracked}/{len(markers)} marker özneyi TAKİP ediyor "
                 f"(hareketli klip)")
