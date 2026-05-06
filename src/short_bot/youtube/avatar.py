"""Per-channel YouTube avatar (channel logo) — download from channel_info,
cache to data/youtube_credentials/<slug>/avatar.jpg, reuse on subsequent calls.
"""
from __future__ import annotations

from pathlib import Path

import requests


_USER_AGENT = "VurucuTIM/1.0 (avatar fetcher)"


def cache_path(root: Path, slug: str) -> Path:
    return Path(root) / slug / "avatar.jpg"


def has_avatar(root: Path, slug: str) -> bool:
    return cache_path(root, slug).is_file()


def avatar_url_from_info(channel_info: dict) -> str | None:
    """Pick the best thumbnail URL from a YouTube channels().list snippet block."""
    if not channel_info:
        return None
    thumbs = (channel_info.get("snippet", {}) or {}).get("thumbnails", {}) or {}
    for key in ("high", "medium", "default"):
        url = (thumbs.get(key) or {}).get("url")
        if url:
            return url
    return None


def fetch_and_cache_avatar(root: Path, slug: str, channel_info: dict,
                            *, force: bool = False) -> Path | None:
    """Download channel avatar to cache. Returns Path on success or None.
    Idempotent: if cache exists and force=False, returns existing path."""
    target = cache_path(root, slug)
    if target.exists() and not force:
        return target
    url = avatar_url_from_info(channel_info)
    if not url:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, timeout=10,
                             headers={"User-Agent": _USER_AGENT})
        resp.raise_for_status()
        target.write_bytes(resp.content)
        return target
    except Exception:
        return None
