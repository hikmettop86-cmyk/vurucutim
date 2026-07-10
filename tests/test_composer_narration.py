import subprocess
from pathlib import Path

import pytest
from PIL import Image

from short_bot.composer import _build_bg_video_cmd, _build_legacy_cmd, compose_video

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def tiny_frames(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(60):  # 2s @ 30fps
        Image.new("RGB", (1080, 1920), (i * 4, 100, 200)).save(frames / f"frame_{i:05d}.png")
    return frames


def _duration(path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(probe.stdout.strip())


def test_narration_none_keeps_legacy_filter_exactly():
    """Regresyon kalkani: narration yokken filtre grafigi degismemeli."""
    cmd, vmap = _build_legacy_cmd(
        Path("f"), Path("m.mp3"), 30, "ffmpeg", [], 0.7, None, 1.0,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert fc == "[1:a]volume=0.7[aout]"
    assert vmap == "0:v"
    assert "-stream_loop" not in cmd


def test_narration_legacy_loops_music_and_puts_narration_first():
    cmd, _ = _build_legacy_cmd(
        Path("f"), Path("m.mp3"), 30, "ffmpeg", [], 0.12, Path("n.mp3"), 1.0,
    )
    # muzik girdisinden hemen once -stream_loop -1 gelmeli
    i = cmd.index("m.mp3")
    assert cmd[i - 3:i - 1] == ["-stream_loop", "-1"]
    # narration input 2 olarak eklenmeli
    assert cmd[cmd.index("n.mp3") - 1] == "-i"

    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[2:a]volume=1[nar]" in fc
    assert "[1:a]volume=0.12[bgm]" in fc
    assert "[nar][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]" in fc


def test_narration_legacy_with_sfx_appends_after_music():
    from short_bot.composer import SfxOverlay
    sfx = [SfxOverlay(path=Path("w.mp3"), delay_ms=500, volume=0.5)]
    cmd, _ = _build_legacy_cmd(
        Path("f"), Path("m.mp3"), 30, "ffmpeg", sfx, 0.12, Path("n.mp3"), 1.0,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[3:a]adelay=500|500,volume=0.5[sfx0]" in fc
    assert "[nar][bgm][sfx0]amix=inputs=3:duration=first" in fc


def test_narration_bg_video_indices_shift():
    """bg video yolunda: 0=bg 1=frames 2=music 3=narration 4+=sfx"""
    cmd, vmap = _build_bg_video_cmd(
        Path("f"), Path("m.mp3"), Path("bg.mp4"),
        fps=30, ffmpeg_path="ffmpeg", sfx_overlays=[], music_volume=0.12,
        bg_blur_px=30, bg_dim=0.7, fg_scale=1.0,
        narration_path=Path("n.mp3"), narration_volume=1.0,
    )
    assert vmap == "[outv]"
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[3:a]volume=1[nar]" in fc
    assert "[2:a]volume=0.12[bgm]" in fc
    assert "[nar][bgm]amix=inputs=2:duration=first" in fc


def test_compose_with_narration_produces_audio(tmp_path, tiny_frames):
    """2sn kare + 2sn muzik + 2sn anlatim -> ~2sn video, ses akisi var."""
    music = FIX / "music_sample_2s.mp3"
    narration = FIX / "music_sample_2s.mp3"   # ses fixture'i olarak yeniden kullanilir
    out = tmp_path / "out.mp4"

    compose_video(tiny_frames, music, out, fps=30, ffmpeg_path="ffmpeg",
                  narration_path=narration, music_volume=0.12, duration_s=3)

    assert out.exists() and out.stat().st_size > 0
    assert 1.8 <= _duration(out) <= 2.3

    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert "audio" in streams.stdout


def test_compose_missing_narration_raises(tmp_path, tiny_frames):
    music = FIX / "music_sample_2s.mp3"
    with pytest.raises(FileNotFoundError, match="Narration"):
        compose_video(tiny_frames, music, tmp_path / "o.mp4",
                      narration_path=tmp_path / "yok.mp3")
