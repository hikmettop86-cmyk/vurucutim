"""Atomic writers for data/secrets.yaml.

Read path (load_secrets) lives in pexels.py — kept there to avoid a circular
import; this module only handles writes.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml


def _atomic_write_yaml(path: Path, data: dict) -> None:
    """Write yaml atomically (write to .tmp, rename) so a crash mid-write
    can't leave a half-written secrets file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def update_channel_proxy(secrets_path: Path, slug: str, url: str | None) -> None:
    """Set or clear channel_proxies[slug] in secrets.yaml.

    - url=str  → upsert
    - url=None → remove. If channel_proxies becomes empty, remove the section.

    File created if missing. Other top-level keys are preserved.
    """
    p = Path(secrets_path)
    data: dict = {}
    if p.exists():
        loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    proxies = dict(data.get("channel_proxies") or {})
    if url is None:
        proxies.pop(slug, None)
    else:
        proxies[slug] = url
    if proxies:
        data["channel_proxies"] = proxies
    else:
        data.pop("channel_proxies", None)
    _atomic_write_yaml(p, data)


def update_openai_api_key(secrets_path: Path, key: str | None) -> None:
    """Set or clear top-level openai_api_key in secrets.yaml.

    - key=str  → upsert
    - key=None → remove

    File created if missing. Other top-level keys are preserved.
    """
    p = Path(secrets_path)
    data: dict = {}
    if p.exists():
        loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    if key is None:
        data.pop("openai_api_key", None)
    else:
        data["openai_api_key"] = key
    _atomic_write_yaml(p, data)


def update_youtube_api_key(secrets_path: Path, key: str | None) -> None:
    """Set or clear top-level youtube_api_key in secrets.yaml.

    Used by trends.youtube_trending (videos.list chart=mostPopular).
    File created if missing. Other top-level keys are preserved.
    """
    p = Path(secrets_path)
    data: dict = {}
    if p.exists():
        loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    if key is None:
        data.pop("youtube_api_key", None)
    else:
        data["youtube_api_key"] = key
    _atomic_write_yaml(p, data)
