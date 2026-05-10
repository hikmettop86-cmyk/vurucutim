"""Article body extractor — trafilatura with HTTP error / empty-body handling."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

import requests
import trafilatura


class _OGImageParser(HTMLParser):
    """Collect og:image and twitter:image meta tag content values."""

    def __init__(self) -> None:
        super().__init__()
        self.og_image: str | None = None
        self.twitter_image: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        d = {k.lower(): (v or "") for k, v in attrs}
        key = (d.get("property") or d.get("name") or "").lower()
        content = d.get("content")
        if not content:
            return
        if key == "og:image" and self.og_image is None:
            self.og_image = content
        elif key == "twitter:image" and self.twitter_image is None:
            self.twitter_image = content


def extract_og_image_url(article_url: str, *, timeout: int = 15) -> str | None:
    """Fetch an article URL and return its og:image (or twitter:image fallback).

    Why: Google News RSS supplies a generic publisher logo as the thumbnail,
    so the same image keeps appearing across unrelated stories. The publisher's
    own og:image meta tag is the actual hero photo of the article.

    Returns absolute URL, or None on missing meta / HTTP failure / network error.
    """
    try:
        r = requests.get(
            article_url, timeout=timeout,
            headers={"User-Agent": "short-bot/0.1"},
        )
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.text:
        return None

    parser = _OGImageParser()
    try:
        parser.feed(r.text)
    except Exception:
        return None

    raw = parser.og_image or parser.twitter_image
    if not raw:
        return None
    return urljoin(article_url, raw)


def extract_article(
    url: str,
    *,
    max_chars: int = 2000,
    timeout: int = 15,
) -> str | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "short-bot/0.1"})
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None

    text = trafilatura.extract(
        r.text,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text:
        return None

    text = text.strip()
    if len(text) < 30:                    # likely paywall/login wall
        return None
    if len(text) > max_chars:
        # truncate at last full sentence
        truncated = text[:max_chars]
        last = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        if last > max_chars // 2:
            text = truncated[:last + 1]
        else:
            text = truncated
    return text
