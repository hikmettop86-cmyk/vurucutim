import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from short_bot.composer import compose_video


@pytest.fixture
def tiny_frames(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(60):  # 2s @ 30fps
        Image.new("RGB", (1080, 1920), (i * 4, 100, 200)).save(frames / f"frame_{i:05d}.png")
    return frames


def test_compose_video_creates_mp4(tmp_path, tiny_frames):
    music = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    out = tmp_path / "out.mp4"
    result = compose_video(tiny_frames, music, out, fps=30, ffmpeg_path="ffmpeg")
    assert result == out
    assert out.exists() and out.stat().st_size > 0


def test_compose_video_duration_matches_frames(tmp_path, tiny_frames):
    music = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    out = tmp_path / "out.mp4"
    compose_video(tiny_frames, music, out, fps=30, ffmpeg_path="ffmpeg")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True, check=True,
    )
    duration = float(probe.stdout.strip())
    assert 1.8 <= duration <= 2.2  # 60 frames / 30fps = 2s
