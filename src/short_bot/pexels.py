"""Pexels Videos API client + archetype-pool query selector + secret resolver."""
from __future__ import annotations

import hashlib
import logging
import os
import random
from pathlib import Path
from typing import Literal

import requests
import yaml
from pydantic import BaseModel


def load_secrets(secrets_path: Path) -> dict:
    """Return parsed YAML dict from secrets_path, or {} if file missing/empty."""
    p = Path(secrets_path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def resolve_pexels_api_key(secrets: dict) -> str:
    """Resolve the Pexels API key. Env var PEXELS_API_KEY beats secrets dict."""
    return os.environ.get("PEXELS_API_KEY") or secrets.get("pexels_api_key") or ""


ARCHETYPE_BG_QUERIES: dict[str, list[str]] = {
    "newscast":  ["newsroom blur", "studio lights motion", "news ticker abstract"],
    "tabloid":   ["paparazzi flash", "neon city night", "magazine pages turning"],
    "magazine":  ["soft fabric texture", "ink water swirl", "warm bokeh"],
    "kinetic":   ["geometric motion", "abstract neon lines", "particle wave"],
    "dark-tech": ["circuit board glow", "matrix code rain", "server room cyan"],
    "stadium":   ["stadium lights night", "crowd cheering blur", "grass pitch zoom"],
    "meme":      ["confetti pop", "colorful gradient swirl", "cartoon background"],
}


def pick_query_for_archetype(archetype: str) -> str:
    """Random pick from the pool. Unknown archetype → generic fallback."""
    pool = ARCHETYPE_BG_QUERIES.get(archetype)
    if not pool:
        return "abstract motion background"
    return random.choice(pool)


logger = logging.getLogger(__name__)

_PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"


class PexelsCandidate(BaseModel):
    id: int
    url: str          # highest-resolution mp4 link
    duration_s: int


def _pick_best_mp4(video_files: list[dict]) -> str | None:
    """From a Pexels video's file list, return the highest-resolution mp4 link."""
    mp4s = [
        f for f in video_files
        if f.get("file_type") == "video/mp4" and f.get("link")
    ]
    if not mp4s:
        return None
    mp4s.sort(key=lambda f: (f.get("width", 0) * f.get("height", 0)), reverse=True)
    return mp4s[0]["link"]


def search_videos(
    query: str,
    api_key: str,
    *,
    max_results: int = 5,
    orientation: Literal["portrait", "landscape", "square"] = "portrait",
    timeout_s: int = 15,
) -> list[PexelsCandidate]:
    """Search Pexels Videos. Returns [] on any error or empty result."""
    if not api_key:
        return []
    try:
        r = requests.get(
            _PEXELS_SEARCH_URL,
            headers={"Authorization": api_key},
            params={"query": query, "orientation": orientation, "per_page": max_results},
            timeout=timeout_s,
        )
    except requests.RequestException as e:
        logger.warning(f"pexels search request failed: {e}")
        return []
    if r.status_code != 200:
        logger.warning(f"pexels search HTTP {r.status_code}: {r.text[:200]}")
        return []
    payload = r.json() or {}
    out: list[PexelsCandidate] = []
    for v in payload.get("videos", []):
        url = _pick_best_mp4(v.get("video_files", []))
        if not url:
            continue
        out.append(PexelsCandidate(
            id=int(v.get("id", 0)),
            url=url,
            duration_s=int(v.get("duration", 0)),
        ))
    return out


def download_video(url: str, cache_dir: Path, *, timeout_s: int = 60) -> Path | None:
    """Stream-download to cache_dir/<sha1>.mp4. Idempotent. Returns None on failure."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    out = cache_dir / f"{key}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    try:
        with requests.get(url, stream=True, timeout=timeout_s) as r:
            if r.status_code != 200:
                logger.warning(f"pexels download HTTP {r.status_code} for {url[:80]}")
                return None
            with open(out, "wb") as fh:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
    except requests.RequestException as e:
        logger.warning(f"pexels download failed for {url[:80]}: {e}")
        if out.exists():
            out.unlink(missing_ok=True)
        return None
    return out
