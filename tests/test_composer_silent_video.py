"""Tests for compose_video_from_silent_video — the Remotion-side pipeline
counterpart to compose_video. Verifies it:
  - skips the PNG frame stage and accepts an MP4 input
  - builds the right ffmpeg input order (silent video, music, then SFX)
  - threads bg_video / SFX / duration_s / music_volume correctly
  - errors on missing inputs
"""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.composer import (
    SfxOverlay,
    compose_video_from_silent_video,
)


def _setup_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    silent = tmp_path / "silent.mp4"
    silent.write_bytes(b"\x00" * 4)
    music = tmp_path / "m.mp3"
    music.write_bytes(b"ID3")
    out = tmp_path / "out.mp4"
    return silent, music, out


def _ok_proc():
    p = MagicMock()
    p.returncode = 0
    p.stderr = ""
    return p


def test_uses_silent_video_as_input_not_png_seq(tmp_path):
    """Critical: the ffmpeg command must take an MP4 input — never reference
    `frame_%05d.png` (that would silently fall back to the HTML pipeline)."""
    silent, music, out = _setup_inputs(tmp_path)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video_from_silent_video(silent, music, out)
    cmd = captured["cmd"]
    assert str(silent) in cmd
    # No PNG frame pattern
    joined = " ".join(cmd)
    assert "frame_%05d.png" not in joined
    assert "-framerate" not in cmd  # only legacy frame path needs framerate


def test_raises_when_silent_video_missing(tmp_path):
    _, music, out = _setup_inputs(tmp_path)
    with pytest.raises(FileNotFoundError, match="Silent video"):
        compose_video_from_silent_video(tmp_path / "no-such.mp4", music, out)


def test_raises_when_music_missing(tmp_path):
    silent, _, out = _setup_inputs(tmp_path)
    with pytest.raises(FileNotFoundError, match="Music"):
        compose_video_from_silent_video(silent, tmp_path / "no-such.mp3", out)


def test_raises_when_bg_video_missing(tmp_path):
    silent, music, out = _setup_inputs(tmp_path)
    with pytest.raises(FileNotFoundError, match="BG video"):
        compose_video_from_silent_video(
            silent, music, out, bg_video_path=tmp_path / "no-such.mp4"
        )


def test_propagates_ffmpeg_failure(tmp_path):
    silent, music, out = _setup_inputs(tmp_path)
    bad = MagicMock(returncode=42, stderr="ffmpeg said no")
    with patch("short_bot.composer.subprocess.run", return_value=bad):
        with pytest.raises(RuntimeError, match="exit 42"):
            compose_video_from_silent_video(silent, music, out)


def test_duration_s_inserts_t_flag(tmp_path):
    silent, music, out = _setup_inputs(tmp_path)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video_from_silent_video(silent, music, out, duration_s=8)
    cmd = captured["cmd"]
    # -t must come immediately after [binary, -y]
    assert cmd[2:4] == ["-t", "8"]


def test_sfx_added_after_music_input(tmp_path):
    silent, music, out = _setup_inputs(tmp_path)
    sfx_path = tmp_path / "ding.wav"
    sfx_path.write_bytes(b"\x00")
    sfx = [SfxOverlay(path=sfx_path, delay_ms=200, volume=0.5)]
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video_from_silent_video(silent, music, out, sfx_overlays=sfx)

    cmd = captured["cmd"]
    # Input order: silent video (0), music (1), SFX (2)
    silent_idx = cmd.index(str(silent))
    music_idx = cmd.index(str(music))
    sfx_idx = cmd.index(str(sfx_path))
    assert silent_idx < music_idx < sfx_idx


def test_bg_video_path_inserts_stream_loop(tmp_path):
    """With bg_video set, the bg video is input 0 (looped), silent video 1."""
    silent, music, out = _setup_inputs(tmp_path)
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"\x00" * 4)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video_from_silent_video(silent, music, out, bg_video_path=bg)
    cmd = captured["cmd"]
    assert "-stream_loop" in cmd
    # bg should be first input
    bg_idx = cmd.index(str(bg))
    silent_idx = cmd.index(str(silent))
    assert bg_idx < silent_idx
