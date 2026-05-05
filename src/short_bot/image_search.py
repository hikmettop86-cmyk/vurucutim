"""DuckDuckGo image search for fallback photo-band backgrounds."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    title: str
    source_domain: str
    width: int | None
    height: int | None
    thumbnail: str | None  # smaller preview URL (for cheap LLM glance if needed)


_BLOCKED_DOMAINS = {
    "pinterest.com", "pinimg.com",  # often broken hot-link
    "lookaside.fbsbx.com",          # facebook CDN
}


def search_images(
    query: str,
    *,
    max_results: int = 5,
    min_width: int = 800,
    safesearch: str = "moderate",
) -> list[ImageCandidate]:
    """Return up to max_results image candidates ordered by DDG relevance.

    Filters: width >= min_width, blocked domains skipped.
    """
    if DDGS is None:
        logger.error("duckduckgo-search not installed")
        raise RuntimeError("duckduckgo-search not installed")

    out: list[ImageCandidate] = []
    try:
        with DDGS() as ddgs:
            results = ddgs.images(
                query,
                safesearch=safesearch,
                size="Large",       # prefer large images
                max_results=max_results * 4,  # over-fetch, we filter
            )
    except Exception as e:
        logger.warning(f"DDG image search failed: {e}")
        return []

    for r in results or []:
        url = r.get("image") or ""
        if not url:
            continue
        domain = urlparse(url).netloc.lower().replace("www.", "")
        if any(bd in domain for bd in _BLOCKED_DOMAINS):
            continue
        w = r.get("width")
        h = r.get("height")
        if w and w < min_width:
            continue
        out.append(ImageCandidate(
            url=url,
            title=r.get("title", "") or "",
            source_domain=domain,
            width=w,
            height=h,
            thumbnail=r.get("thumbnail"),
        ))
        if len(out) >= max_results:
            break
    return out
