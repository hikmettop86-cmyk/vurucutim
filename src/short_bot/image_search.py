"""DuckDuckGo image search for fallback photo-band backgrounds."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    from ddgs import DDGS
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
    max_attempts: int = 3,
) -> list[ImageCandidate]:
    """Return up to max_results image candidates ordered by DDG relevance.

    Filters: width >= min_width, blocked domains skipped.
    Retries up to max_attempts with exponential backoff on rate-limit / network errors.
    """
    if DDGS is None:
        logger.error("ddgs package not installed")
        raise RuntimeError("ddgs package not installed")

    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with DDGS() as ddgs:
                raw_results = list(ddgs.images(
                    query,
                    safesearch=safesearch,
                    size="Large",
                    max_results=max_results * 4,
                ))
            return _filter_results(raw_results, min_width=min_width, max_results=max_results)
        except Exception as e:
            err_text = str(e).lower()
            last_err = e
            if "ratelimit" in err_text or "403" in err_text or "429" in err_text:
                # exponential backoff: 4s, 8s, 16s
                if attempt < max_attempts:
                    time.sleep(4 * (2 ** (attempt - 1)))
                    continue
            logger.warning(f"DDG image search failed (attempt {attempt}): {e}")
            if attempt < max_attempts:
                time.sleep(2)
                continue
    logger.warning(f"DDG image search exhausted retries: {last_err}")
    return []


def _filter_results(raw_results, *, min_width: int, max_results: int) -> list[ImageCandidate]:
    out: list[ImageCandidate] = []
    for r in raw_results or []:
        url = r.get("image") or ""
        if not url:
            continue
        domain = urlparse(url).netloc.lower().replace("www.", "")
        if any(bd in domain for bd in _BLOCKED_DOMAINS):
            continue
        try:
            w = int(r.get("width")) if r.get("width") is not None else None
        except (ValueError, TypeError):
            w = None
        try:
            h = int(r.get("height")) if r.get("height") is not None else None
        except (ValueError, TypeError):
            h = None
        if w is not None and w < min_width:
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
