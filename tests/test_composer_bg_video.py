from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.composer import compose_video


def _setup_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_00001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    music = tmp_path / "m.mp3"
    music.write_bytes(b"ID3")
    out = tmp_path / "out.mp4"
    return frames, music, out


def _ok_proc():
    p = MagicMock()
    p.returncode = 0
    p.stderr = ""
    return p


def test_compose_without_bg_video_keeps_single_input_pipeline(tmp_path):
    frames, music, out = _setup_inputs(tmp_path)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video(frames, music, out)
    cmd = captured["cmd"]
    # No bg video → only frames + music as inputs (2 -i flags)
    assert cmd.count("-i") == 2
    assert "overlay=" not in " ".join(cmd)


def test_compose_with_bg_video_emits_three_inputs_and_overlay(tmp_path):
    frames, music, out = _setup_inputs(tmp_path)
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"fake-mp4")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video(
            frames, music, out,
            bg_video_path=bg, bg_blur_px=25, bg_dim=0.5, fg_scale=0.88,
        )
    cmd = captured["cmd"]
    cmd_str = " ".join(cmd)
    # Three -i inputs: bg, frames, music
    assert cmd.count("-i") == 3
    # bg input must come first (and use stream_loop -1 for indefinite loop)
    assert "-stream_loop" in cmd
    bg_idx = cmd.index(str(bg))
    frames_idx = cmd.index(str(frames / "frame_%05d.png"))
    music_idx = cmd.index(str(music))
    assert bg_idx < frames_idx < music_idx
    # Filter graph references
    assert "gblur=sigma=25" in cmd_str
    assert "scale=iw*0.88:ih*0.88" in cmd_str
    assert "overlay=" in cmd_str


def test_compose_with_bg_video_and_fg_scale_one_still_emits_overlay(tmp_path):
    """fg_scale=1.0 with a bg video means letterboxed-but-same-size foreground.
    The overlay path should still run (background is the whole point)."""
    frames, music, out = _setup_inputs(tmp_path)
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"x")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video(frames, music, out, bg_video_path=bg, fg_scale=1.0)
    cmd_str = " ".join(captured["cmd"])
    assert "overlay=" in cmd_str
    assert "scale=iw*1.0:ih*1.0" in cmd_str


def test_compose_with_bg_video_raises_when_bg_missing(tmp_path):
    frames, music, out = _setup_inputs(tmp_path)
    missing_bg = tmp_path / "nope.mp4"
    with pytest.raises(FileNotFoundError):
        compose_video(frames, music, out, bg_video_path=missing_bg)


def test_compose_with_bg_video_propagates_ffmpeg_failure(tmp_path):
    frames, music, out = _setup_inputs(tmp_path)
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"x")

    fail = MagicMock()
    fail.returncode = 1
    fail.stderr = "synthetic error"

    with patch("short_bot.composer.subprocess.run", return_value=fail):
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            compose_video(frames, music, out, bg_video_path=bg)
