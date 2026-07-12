"""Reel montajı: çok-klip hızlı kesme + zoom-punch + overlay + ses miksi.

PoC'de (scratchpad/poc/make_poc2.py) doğrulanmış ffmpeg mantığı.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

W, H = 1080, 1920
_ZOOMPAN = ("zoompan=z='if(lte(on,9),1.16-0.0178*on,min(1.06,1.0+0.0006*(on-9)))'"
            ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30")


def _run(cmd) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


# Açılış kalıp-kırıcı: sert zoom-punch (1.25 → 1.0, ~1.5sn). İzleyici ilk
# saniyede kalır ya da kaçar — düz açılış retention sızdırır.
_PUNCH = ("zoompan=z='if(lte(on,45),1.25-0.0055*on,1.0)'"
          ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30")


def _normalize_segment(clip: Path, span_s: float, out: Path, *, fps: int,
                       ffmpeg: str, zoom: bool, start_s: float = 0.0,
                       punch: bool = False) -> None:
    base = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    zoom_f = _PUNCH if punch else _ZOOMPAN
    vf_zoom = f"{base},{zoom_f},format=yuv420p"
    vf_plain = f"{base},fps={fps},format=yuv420p"
    # start_s: AYNI klibin farklı anından başla (alt-kesim çeşitliliği) — hızlı
    # kesimde bir beat'in alt-kesimleri aynı klibi tekrar kullanabilir.
    seek = ["-ss", f"{start_s:.3f}"] if start_s > 0 else []
    for vf in ([vf_zoom, vf_plain] if (zoom or punch) else [vf_plain]):
        p = _run([ffmpeg, "-y", "-stream_loop", "-1", *seek, "-i", str(clip),
                  "-t", f"{span_s:.3f}", "-vf", vf, "-an",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)])
        if p.returncode == 0:
            return
    raise RuntimeError(f"segment normalize başarısız ({clip.name}): {p.stderr[-500:]}")


def assemble_reel(
    *, clip_paths: list[Path], seg_spans: list[tuple[float, float]],
    frames_dir: Path, narration_path: Path, music_path: Path | None,
    out_path: Path, cut_times: list[float], duration_s: float,
    fps: int = 30, ffmpeg_path: str = "ffmpeg", music_volume: float = 0.10,
    narration_volume: float = 1.0, sfx_at_cut: list | None = None,
    zoom: bool = True, clip_starts: list | None = None,
    hook_punch: bool = False,
) -> Path:
    """Segment klipleri + overlay + ses → mp4. clip_paths ve seg_spans aynı boyda."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for c in clip_paths:
        if not Path(c).exists():
            raise FileNotFoundError(f"Reel klibi yok: {c}")
    if not Path(narration_path).exists():
        raise FileNotFoundError(f"Anlatım sesi yok: {narration_path}")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        seg_files = []
        starts = list(clip_starts or [])
        for i, (clip, (a, b)) in enumerate(zip(clip_paths, seg_spans)):
            span = max(0.5, b - a)
            sf = td / f"seg_{i}.mp4"
            _normalize_segment(Path(clip), span, sf, fps=fps,
                               ffmpeg=ffmpeg_path, zoom=zoom,
                               start_s=(starts[i] if i < len(starts) else 0.0),
                               punch=(hook_punch and i == 0))
            seg_files.append(sf)
        lst = td / "concat.txt"
        lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in seg_files),
                       encoding="utf-8")
        footage = td / "footage.mp4"
        p = _run([ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                  "-c", "copy", str(footage)])
        if p.returncode != 0:
            raise RuntimeError(f"concat başarısız: {p.stderr[-500:]}")

        cmd = [ffmpeg_path, "-y", "-i", str(footage),
               "-framerate", str(fps), "-i", str(Path(frames_dir) / "f_%05d.png"),
               "-i", str(narration_path)]
        parts = ["[0:v][1:v]overlay=0:0[v]", "[2:a]volume={:g}[nar]".format(narration_volume)]
        labels = ["[nar]"]
        idx = 3
        if music_path is not None:
            cmd += ["-stream_loop", "-1", "-i", str(music_path)]
            parts.append(f"[{idx}:a]volume={music_volume:g}[bgm]")
            labels.append("[bgm]")
            idx += 1
        if sfx_at_cut and cut_times:
            for k, ct in enumerate(cut_times):
                if k >= len(sfx_at_cut) or sfx_at_cut[k] is None:
                    continue
                cmd += ["-i", str(sfx_at_cut[k])]
                parts.append(f"[{idx}:a]adelay={int(ct*1000)}|{int(ct*1000)},volume=0.6[wh{k}]")
                labels.append(f"[wh{k}]")
                idx += 1
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:"
                     f"duration=first:dropout_transition=0:normalize=0[a]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
                "-t", f"{duration_s:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(out_path)]
        p = _run(cmd)
        if p.returncode != 0:
            raise RuntimeError(f"final montaj başarısız: {p.stderr[-800:]}")
    return out_path
