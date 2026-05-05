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
) -> Path:
    """Compose final video. If sfx_overlays provided, mix them over music with delays."""
    frames_dir = Path(frames_dir)
    music_path = Path(music_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not any(frames_dir.glob("frame_*.png")):
        raise FileNotFoundError(f"No frames in {frames_dir}")
    if not music_path.exists():
        raise FileNotFoundError(f"Music not found: {music_path}")

    sfx_overlays = sfx_overlays or []
    # Validate SFX files
    for s in sfx_overlays:
        if not Path(s.path).exists():
            raise FileNotFoundError(f"SFX not found: {s.path}")

    # Build base command
    cmd = [
        ffmpeg_path, "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-i", str(music_path),
    ]
    for s in sfx_overlays:
        cmd += ["-i", str(s.path)]

    # Audio filter graph
    if not sfx_overlays:
        # Just music with volume tweak
        filter_complex = f"[1:a]volume={music_volume}[aout]"
    else:
        # Music + delayed SFX → amix
        parts = [f"[1:a]volume={music_volume}[bgm]"]
        labels = ["[bgm]"]
        for i, s in enumerate(sfx_overlays):
            in_idx = 2 + i  # input 2 onwards are SFX
            tag = f"sfx{i}"
            parts.append(
                f"[{in_idx}:a]adelay={s.delay_ms}|{s.delay_ms},volume={s.volume}[{tag}]"
            )
            labels.append(f"[{tag}]")
        n = len(labels)
        parts.append(f"{''.join(labels)}amix=inputs={n}:duration=first:dropout_transition=0[aout]")
        filter_complex = ";".join(parts)

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "0:v",
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
