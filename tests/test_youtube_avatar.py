from pathlib import Path
from unittest.mock import patch, MagicMock

from short_bot.youtube.avatar import (
    cache_path, has_avatar, avatar_url_from_info, fetch_and_cache_avatar,
)


def test_cache_path_per_channel(tmp_path):
    p = cache_path(tmp_path / "creds", "ch")
    assert p == tmp_path / "creds" / "ch" / "avatar.jpg"


def test_avatar_url_picks_best_quality():
    info = {"snippet": {"thumbnails": {
        "default": {"url": "http://x/d.jpg"},
        "medium": {"url": "http://x/m.jpg"},
        "high": {"url": "http://x/h.jpg"},
    }}}
    assert avatar_url_from_info(info) == "http://x/h.jpg"


def test_avatar_url_falls_back_when_high_missing():
    info = {"snippet": {"thumbnails": {
        "default": {"url": "http://x/d.jpg"},
        "medium": {"url": "http://x/m.jpg"},
    }}}
    assert avatar_url_from_info(info) == "http://x/m.jpg"


def test_avatar_url_returns_none_when_no_thumbs():
    assert avatar_url_from_info({}) is None
    assert avatar_url_from_info({"snippet": {}}) is None
    assert avatar_url_from_info(None) is None


def test_has_avatar(tmp_path):
    assert not has_avatar(tmp_path / "creds", "ch")
    (tmp_path / "creds" / "ch").mkdir(parents=True)
    (tmp_path / "creds" / "ch" / "avatar.jpg").write_bytes(b"\x00")
    assert has_avatar(tmp_path / "creds", "ch")


def test_fetch_downloads_when_missing(tmp_path):
    info = {"snippet": {"thumbnails": {"high": {"url": "http://x/h.jpg"}}}}
    with patch("short_bot.youtube.avatar.requests.get") as m:
        m.return_value = MagicMock(status_code=200, content=b"\xff\xd8jpegdata")
        result = fetch_and_cache_avatar(tmp_path / "creds", "ch", info)
    assert result is not None
    assert result.exists()
    assert result.read_bytes() == b"\xff\xd8jpegdata"


def test_fetch_skips_when_cache_exists(tmp_path):
    d = tmp_path / "creds" / "ch"; d.mkdir(parents=True)
    (d / "avatar.jpg").write_bytes(b"existing")
    info = {"snippet": {"thumbnails": {"high": {"url": "http://x/h.jpg"}}}}
    with patch("short_bot.youtube.avatar.requests.get") as m:
        result = fetch_and_cache_avatar(tmp_path / "creds", "ch", info)
    assert result is not None
    assert m.call_count == 0  # no network call
    assert result.read_bytes() == b"existing"


def test_fetch_force_redownloads(tmp_path):
    d = tmp_path / "creds" / "ch"; d.mkdir(parents=True)
    (d / "avatar.jpg").write_bytes(b"old")
    info = {"snippet": {"thumbnails": {"high": {"url": "http://x/h.jpg"}}}}
    with patch("short_bot.youtube.avatar.requests.get") as m:
        m.return_value = MagicMock(status_code=200, content=b"new")
        result = fetch_and_cache_avatar(tmp_path / "creds", "ch", info, force=True)
    assert result.read_bytes() == b"new"


def test_fetch_handles_network_error(tmp_path):
    info = {"snippet": {"thumbnails": {"high": {"url": "http://x/h.jpg"}}}}
    import requests
    with patch("short_bot.youtube.avatar.requests.get",
                side_effect=requests.exceptions.RequestException("boom")):
        result = fetch_and_cache_avatar(tmp_path / "creds", "ch", info)
    assert result is None
