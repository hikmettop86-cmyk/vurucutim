import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.assets import download_and_blur_thumb, pick_music


def test_download_and_blur_thumb_writes_blurred(tmp_path):
    src = (Path(__file__).parent / "fixtures" / "thumb_sample.jpg").read_bytes()
    cache = tmp_path / "cache"
    with patch("short_bot.assets.requests.get") as m:
        r = MagicMock()
        r.status_code = 200
        r.content = src
        m.return_value = r
        out = download_and_blur_thumb("http://x/thumb.jpg", cache, blur_radius=8)
    assert out is not None
    assert out.exists()
    assert out.suffix == ".jpg"


def test_download_and_blur_thumb_returns_none_on_404(tmp_path):
    with patch("short_bot.assets.requests.get") as m:
        r = MagicMock()
        r.status_code = 404
        m.return_value = r
        assert download_and_blur_thumb("http://x", tmp_path) is None


def test_download_and_blur_thumb_returns_none_on_invalid_image(tmp_path):
    with patch("short_bot.assets.requests.get") as m:
        r = MagicMock()
        r.status_code = 200
        r.content = b"not an image"
        m.return_value = r
        assert download_and_blur_thumb("http://x", tmp_path) is None


def test_pick_music_returns_random_file(tmp_path):
    mood_dir = tmp_path / "music" / "breaking"
    mood_dir.mkdir(parents=True)
    src = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    (mood_dir / "a.mp3").write_bytes(src.read_bytes())
    (mood_dir / "b.mp3").write_bytes(src.read_bytes())
    picked = pick_music(tmp_path / "music", mood="breaking")
    assert picked.name in {"a.mp3", "b.mp3"}


def test_pick_music_falls_back_to_neutral(tmp_path):
    neutral = tmp_path / "music" / "neutral"
    neutral.mkdir(parents=True)
    src = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    (neutral / "n.mp3").write_bytes(src.read_bytes())
    picked = pick_music(tmp_path / "music", mood="upbeat")
    assert picked.name == "n.mp3"


def test_pick_music_raises_when_nothing_available(tmp_path):
    (tmp_path / "music").mkdir()
    with pytest.raises(FileNotFoundError):
        pick_music(tmp_path / "music", mood="breaking")
