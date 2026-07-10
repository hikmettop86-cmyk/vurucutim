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
    duration_s: int | None = None,
    narration_path: Path | None = None,
    narration_volume: float = 1.0,
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

    if narration_path is not None and not Path(narration_path).exists():
        raise FileNotFoundError(f"Narration not found: {narration_path}")

    if bg_video_path is None:
        cmd, video_map = _build_legacy_cmd(
            frames_dir, music_path, fps, ffmpeg_path, sfx_overlays, music_volume,
            narration_path, narration_volume,
        )
    else:
        cmd, video_map = _build_bg_video_cmd(
            frames_dir, music_path, Path(bg_video_path),
            fps=fps, ffmpeg_path=ffmpeg_path,
            sfx_overlays=sfx_overlays, music_volume=music_volume,
            bg_blur_px=bg_blur_px, bg_dim=bg_dim, fg_scale=fg_scale,
            narration_path=narration_path, narration_volume=narration_volume,
        )

    # Global duration cap (defense-in-depth: relying on -shortest is fragile
    # when overlay filter's default repeatlast=1 keeps emitting frames after
    # the foreground PNG seq ends).
    if duration_s is not None:
        # Insert "-t {duration_s}" immediately after the binary + "-y"
        # i.e., positions 0 and 1 are [ffmpeg_path, "-y"]; insert at 2.
        cmd[2:2] = ["-t", str(duration_s)]

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


def _build_voiced_audio_chain(
    *, music_idx: int, narration_idx: int, sfx_start_idx: int,
    sfx_overlays, music_volume: float, narration_volume: float,
) -> str:
    """Anlatım birinci girdi → amix duration=first çıktı süresini anlatıma bağlar.

    normalize=0: amix varsayılan olarak her girdiyi 1/n ile böler; anlatımın
    sesi yarıya düşmesin diye kapatılır. Müzik zaten music_volume ile kısık.
    """
    parts = [
        f"[{narration_idx}:a]volume={narration_volume:g}[nar]",
        f"[{music_idx}:a]volume={music_volume:g}[bgm]",
    ]
    labels = ["[nar]", "[bgm]"]
    for i, s in enumerate(sfx_overlays):
        tag = f"sfx{i}"
        parts.append(
            f"[{sfx_start_idx + i}:a]adelay={s.delay_ms}|{s.delay_ms},"
            f"volume={s.volume}[{tag}]"
        )
        labels.append(f"[{tag}]")
    parts.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:"
        f"dropout_transition=0:normalize=0[aout]"
    )
    return ";".join(parts)


def _build_legacy_cmd(frames_dir, music_path, fps, ffmpeg_path,
                      sfx_overlays, music_volume,
                      narration_path=None, narration_volume=1.0) -> tuple[list[str], str]:
    """Single-stream pipeline (no bg video). Returns (cmd-prefix, video-map-label).

    Inputs: 0 frames, 1 music, [2 narration], then SFX.
    Anlatım varken müzik döngüye alınır (kısa mp3 uzun anlatımın altında bitmesin).
    """
    cmd = [
        ffmpeg_path, "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
    ]
    if narration_path is not None:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", str(music_path)]
    if narration_path is not None:
        cmd += ["-i", str(narration_path)]
    for s in sfx_overlays:
        cmd += ["-i", str(s.path)]

    if narration_path is not None:
        filter_complex = _build_voiced_audio_chain(
            music_idx=1, narration_idx=2, sfx_start_idx=3,
            sfx_overlays=sfx_overlays, music_volume=music_volume,
            narration_volume=narration_volume,
        )
    elif not sfx_overlays:
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
    narration_path=None, narration_volume=1.0,
) -> tuple[list[str], str]:
    """Two-stream pipeline. Returns (cmd-prefix, video-map-label).

    Inputs (in order):
      0: bg video (looped)
      1: frame PNG seq
      2: music
      3: optional narration
      4+: optional SFX
    """
    cmd = [
        ffmpeg_path, "-y",
        "-stream_loop", "-1",
        "-i", str(bg_video_path),
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
    ]
    if narration_path is not None:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", str(music_path)]
    if narration_path is not None:
        cmd += ["-i", str(narration_path)]
    for s in sfx_overlays:
        cmd += ["-i", str(s.path)]

    # Brightness expression: dim=0 → black (-1), dim=1 → unchanged (0).
    # Saturation kept near full so the BG remains colorful even when dimmed —
    # otherwise the result looks like a black-and-grey video and users
    # complain "hep siyah video". 0.85 default keeps colors vivid.
    brightness = -(1.0 - bg_dim)
    saturation = max(0.85, bg_dim)

    # Video filter graph
    bg_chain = (
        f"[0:v]gblur=sigma={bg_blur_px},"
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,"
        f"eq=brightness={brightness:.2f}:saturation={saturation:.2f}[bg]"
    )
    fg_chain = f"[1:v]scale=iw*{fg_scale}:ih*{fg_scale},format=rgba[fg]"
    overlay_chain = "[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1:format=auto[outv]"

    # Audio (same logic as legacy, but music is input 2 and SFX 3+)
    if narration_path is not None:
        audio_chain = _build_voiced_audio_chain(
            music_idx=2, narration_idx=3, sfx_start_idx=4,
            sfx_overlays=sfx_overlays, music_volume=music_volume,
            narration_volume=narration_volume,
        )
    elif not sfx_overlays:
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
