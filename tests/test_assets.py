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


def _seed_mp3(p: Path):
    src = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(src.read_bytes())


def test_pick_music_uses_channel_dir_mood_subfolder(tmp_path):
    """assets/music/<slug>/<mood>/*.mp3 → preferred over default mood dir."""
    _seed_mp3(tmp_path / "music" / "breaking" / "default.mp3")
    _seed_mp3(tmp_path / "music" / "ask" / "breaking" / "channel.mp3")
    picked = pick_music(tmp_path / "music", mood="breaking", channel_slug="ask")
    assert picked.name == "channel.mp3"


def test_pick_music_uses_channel_flat_dir(tmp_path):
    """assets/music/<slug>/*.mp3 (no mood subfolder) — convenience for users."""
    _seed_mp3(tmp_path / "music" / "neutral" / "default.mp3")
    _seed_mp3(tmp_path / "music" / "ask" / "song1.mp3")
    _seed_mp3(tmp_path / "music" / "ask" / "song2.mp3")
    picked = pick_music(tmp_path / "music", mood="upbeat", channel_slug="ask")
    assert picked.name in {"song1.mp3", "song2.mp3"}


def test_pick_music_falls_back_to_default_when_channel_dir_empty(tmp_path):
    """Empty assets/music/<slug>/ should fall through to default mood dirs."""
    (tmp_path / "music" / "ask").mkdir(parents=True)   # exists but empty
    _seed_mp3(tmp_path / "music" / "neutral" / "default.mp3")
    picked = pick_music(tmp_path / "music", mood="neutral", channel_slug="ask")
    assert picked.name == "default.mp3"


def test_pick_music_no_channel_slug_uses_legacy_path(tmp_path):
    """Calling without channel_slug must behave exactly like before."""
    _seed_mp3(tmp_path / "music" / "neutral" / "n.mp3")
    picked = pick_music(tmp_path / "music", mood="neutral")
    assert picked.name == "n.mp3"
