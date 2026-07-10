from pathlib import Path

import pytest

from short_bot.audio_probe import probe_duration_s

FIXTURE = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"


def test_probe_duration_of_2s_fixture():
    d = probe_duration_s(FIXTURE)
    assert 1.8 <= d <= 2.2


def test_probe_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        probe_duration_s(tmp_path / "yok.mp3")


def test_probe_bad_output_raises(tmp_path):
    f = tmp_path / "x.mp3"
    f.write_bytes(b"not-audio")
    with pytest.raises(RuntimeError, match="ffprobe"):
        probe_duration_s(f)
