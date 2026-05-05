"""Wikimedia Commons image search fallback (no API key, no rate limits to speak of)."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from short_bot.image_search import ImageCandidate

logger = logging.getLogger(__name__)


_API_URL = "https://commons.wikimedia.org/w/api.php"


def search_images_commons(
    query: str,
    *,
    max_results: int = 5,
    min_width: int = 800,
    timeout: int = 15,
) -> list[ImageCandidate]:
    """Search Wikimedia Commons for images matching `query`.

    Two-phase: (1) generator=search to find file titles, (2) imageinfo to get URLs + dims.
    """
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrlimit": max_results * 4,
        "gsrnamespace": 6,                       # File: namespace
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": 1280,                       # ask for ~1280px thumb
    }
    try:
        r = requests.get(_API_URL, params=params, timeout=timeout,
                          headers={"User-Agent": "short-bot/0.1 (https://example.com)"})
    except requests.RequestException as e:
        logger.warning(f"Wikimedia search failed: {e}")
        return []
    if r.status_code != 200:
        logger.warning(f"Wikimedia search HTTP {r.status_code}")
        return []
    data = r.json()
    pages = (data.get("query") or {}).get("pages") or {}
    out: list[ImageCandidate] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        w = info.get("thumbwidth") or info.get("width")
        h = info.get("thumbheight") or info.get("height")
        if w and w < min_width:
            continue
        # Skip SVG / animated / vector formats — keep raster only
        if url.lower().endswith((".svg", ".gif")):
            continue
        out.append(ImageCandidate(
            url=url,
            title=page.get("title", ""),
            source_domain=urlparse(url).netloc.lower().replace("www.", ""),
            width=w,
            height=h,
            thumbnail=info.get("url"),
        ))
        if len(out) >= max_results:
            break
    return out
