import subprocess
from pathlib import Path

import pytest
from PIL import Image

from short_bot.reel_assembler import assemble_reel


def _clip(path, secs=3, color=(80, 120, 60)):
    """Küçük gerçek mp4 üret (renkli, sessiz)."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c=0x{color[0]:02x}{color[1]:02x}{color[2]:02x}:s=640x360:d={secs}:r=30",
         "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, check=True)
    return path


def _frames(d, n):
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 0))
        img.save(d / f"f_{i:05d}.png")
    return d


def test_assemble_produces_video_with_audio(tmp_path):
    clips = [_clip(tmp_path / f"c{i}.mp4", color=(i*30, 100, 80)) for i in range(3)]
    spans = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    frames = _frames(tmp_path / "frames", 90)   # 3s @ 30fps
    music = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    narration = music
    out = tmp_path / "out.mp4"

    result = assemble_reel(
        clip_paths=clips, seg_spans=spans, frames_dir=frames,
        narration_path=narration, music_path=music, out_path=out,
        cut_times=[1.0, 2.0], duration_s=3.0, fps=30,
        music_volume=0.1, whoosh_path=None, zoom=True,
    )
    assert result == out and out.exists() and out.stat().st_size > 0

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "default=nw=1", str(out)],
        capture_output=True, text=True, check=True)
    assert "audio" in probe.stdout
    dur = float([l for l in probe.stdout.splitlines() if l.startswith("duration=")][0].split("=")[1])
    assert 2.7 <= dur <= 3.3


def test_assemble_missing_clip_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        assemble_reel(
            clip_paths=[tmp_path / "yok.mp4"], seg_spans=[(0.0, 1.0)],
            frames_dir=_frames(tmp_path / "f", 30),
            narration_path=Path(__file__).parent / "fixtures" / "music_sample_2s.mp3",
            music_path=None, out_path=tmp_path / "o.mp4",
            cut_times=[], duration_s=1.0)


def test_assemble_zoom_fallback_on_failure(tmp_path, monkeypatch):
    """zoompan patlarsa düz crop'a düşer, yine üretir."""
    clips = [_clip(tmp_path / "c0.mp4")]
    frames = _frames(tmp_path / "frames", 30)
    music = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    out = tmp_path / "out.mp4"
    result = assemble_reel(
        clip_paths=clips, seg_spans=[(0.0, 1.0)], frames_dir=frames,
        narration_path=music, music_path=None, out_path=out,
        cut_times=[], duration_s=1.0, zoom=True)
    assert out.exists()
