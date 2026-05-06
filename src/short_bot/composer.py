"""FFmpeg compose: PNG frames + music + optional SFX overlays → mp4 (H.264, 9:16, AAC)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SfxOverlay:
    path: Path
    delay_ms: int      # when to start playing (relative to video start)
    volume: float = 1.0  # 0.0-1.0+


def compose_video(
    frames_dir: Path,
    music_path: Path,
    out_path: Path,
    *,
    fps: int = 30,
    ffmpeg_path: str = "ffmpeg",
    sfx_overlays: list[SfxOverlay] | None = None,
    music_volume: float = 0.7,
    bg_video_path: Path | None = None,
    bg_blur_px: int = 30,
    bg_dim: float = 0.4,
    fg_scale: float = 1.0,
) -> Path:
    """Compose final video.

    Without bg_video_path: PNG frames + music (+ optional SFX) → mp4 (legacy path).
    With bg_video_path: bg video (looped, blurred, dimmed, cropped 1080x1920)
    underneath PNG frames (scaled by fg_scale, centered) → mp4.
    """
    frames_dir = Path(frames_dir)
    music_path = Path(music_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not any(frames_dir.glob("frame_*.png")):
        raise FileNotFoundError(f"No frames in {frames_dir}")
    if not music_path.exists():
        raise FileNotFoundError(f"Music not found: {music_path}")
    if bg_video_path is not None and not Path(bg_video_path).exists():
        raise FileNotFoundError(f"BG video not found: {bg_video_path}")

    sfx_overlays = sfx_overlays or []
    for s in sfx_overlays:
        if not Path(s.path).exists():
            raise FileNotFoundError(f"SFX not found: {s.path}")

    if bg_video_path is None:
        cmd, video_map = _build_legacy_cmd(
            frames_dir, music_path, fps, ffmpeg_path, sfx_overlays, music_volume,
        )
    else:
        cmd, video_map = _build_bg_video_cmd(
            frames_dir, music_path, Path(bg_video_path),
            fps=fps, ffmpeg_path=ffmpeg_path,
            sfx_overlays=sfx_overlays, music_volume=music_volume,
            bg_blur_px=bg_blur_px, bg_dim=bg_dim, fg_scale=fg_scale,
        )

    cmd += [
        "-map", video_map,
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {proc.stderr[-1500:]}")
    return out_path


def _build_legacy_cmd(frames_dir, music_path, fps, ffmpeg_path,
                      sfx_overlays, music_volume) -> tuple[list[str], str]:
    """Single-stream pipeline (no bg video). Returns (cmd-prefix, video-map-label)."""
    cmd = [
        ffmpeg_path, "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-i", str(music_path),
    ]
    for s in sfx_overlays:
        cmd += ["-i", str(s.path)]

    if not sfx_overlays:
        filter_complex = f"[1:a]volume={music_volume}[aout]"
    else:
        parts = [f"[1:a]volume={music_volume}[bgm]"]
        labels = ["[bgm]"]
        for i, s in enumerate(sfx_overlays):
            in_idx = 2 + i
            tag = f"sfx{i}"
            parts.append(
                f"[{in_idx}:a]adelay={s.delay_ms}|{s.delay_ms},volume={s.volume}[{tag}]"
            )
            labels.append(f"[{tag}]")
        n = len(labels)
        parts.append(
            f"{''.join(labels)}amix=inputs={n}:duration=first:dropout_transition=0[aout]"
        )
        filter_complex = ";".join(parts)

    cmd += ["-filter_complex", filter_complex]
    return cmd, "0:v"


def _build_bg_video_cmd(
    frames_dir, music_path, bg_video_path, *,
    fps, ffmpeg_path, sfx_overlays, music_volume,
    bg_blur_px, bg_dim, fg_scale,
) -> tuple[list[str], str]:
    """Two-stream pipeline. Returns (cmd-prefix, video-map-label).

    Inputs (in order):
      0: bg video (looped)
      1: frame PNG seq
      2: music
      3+: optional SFX
    """
    cmd = [
        ffmpeg_path, "-y",
        "-stream_loop", "-1",
        "-i", str(bg_video_path),
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-i", str(music_path),
    ]
    for s in sfx_overlays:
        cmd += ["-i", str(s.path)]

    # Brightness expression: dim=0 → black (-1), dim=1 → unchanged (0)
    brightness = -(1.0 - bg_dim)

    # Video filter graph
    bg_chain = (
        f"[0:v]gblur=sigma={bg_blur_px},"
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,"
        f"eq=brightness={brightness:.2f}:saturation={bg_dim:.2f}[bg]"
    )
    fg_chain = f"[1:v]scale=iw*{fg_scale}:ih*{fg_scale},format=rgba[fg]"
    overlay_chain = "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto[outv]"

    # Audio (same logic as legacy, but music is input 2 and SFX 3+)
    if not sfx_overlays:
        audio_chain = f"[2:a]volume={music_volume}[aout]"
    else:
        parts = [f"[2:a]volume={music_volume}[bgm]"]
        labels = ["[bgm]"]
        for i, s in enumerate(sfx_overlays):
            in_idx = 3 + i
            tag = f"sfx{i}"
            parts.append(
                f"[{in_idx}:a]adelay={s.delay_ms}|{s.delay_ms},volume={s.volume}[{tag}]"
            )
            labels.append(f"[{tag}]")
        n = len(labels)
        parts.append(
            f"{''.join(labels)}amix=inputs={n}:duration=first:dropout_transition=0[aout]"
        )
        audio_chain = ";".join(parts)

    filter_complex = ";".join([bg_chain, fg_chain, overlay_chain, audio_chain])
    cmd += ["-filter_complex", filter_complex]
    return cmd, "[outv]"
