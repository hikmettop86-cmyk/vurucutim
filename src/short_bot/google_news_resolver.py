"""Resolve a news.google.com redirect URL to the publisher's real URL.

Google News RSS items take the form:
    https://news.google.com/rss/articles/CBMi<base64-payload>?oc=5&hl=...

In 2024 Google replaced the old direct-base64 redirect with an interstitial
page that requires JS to compute a signed forwarding token, so a plain
requests.get does NOT follow through (status 200, body 500KB+ of obfuscated
JS, no meta-refresh, no Location header).

The only reliable way to reach the publisher URL today is to load the page
in a real browser context. Playwright (already a project dep for frame
rendering) handles this in 2-5 seconds.

Failure modes (any -> return None):
  - Not a Google News URL  (caller can just use the input)
  - Playwright import error or browser launch failure
  - Navigation timeout
  - Page redirected to another Google domain (consent.google.com etc.)

Public API:
    is_google_news_url(url) -> bool
    resolve(url, *, timeout_s=8) -> str | None
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def is_google_news_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "news.google.com" or host.endswith(".news.google.com")


def _looks_like_publisher(url: str) -> bool:
    """True if the URL is plausibly an external publisher (not Google itself)."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    google_owned = (
        "google.com", "googleusercontent.com", "youtube.com", "consent.google.com",
    )
    return not any(host == g or host.endswith("." + g) for g in google_owned)


def resolve(url: str, *, timeout_s: int = 8) -> str | None:
    """Return the publisher URL behind a news.google.com redirect, or None.

    For non-google-news input URLs, returns the URL unchanged (no work).
    For google-news input URLs that we cannot resolve, returns None
    (caller must decide whether to give up or use a fallback).
    """
    if not is_google_news_url(url):
        return url

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError as e:
        logger.warning(f"playwright unavailable for google news resolve: {e}")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"
                    ),
                    java_script_enabled=True,
                )
                # Block heavy resources — we only need the redirect, not the
                # final publisher page's CSS/images/fonts/media. This cuts
                # the per-resolve cost from ~12s down to ~3-5s in practice.
                _BLOCK = {"image", "media", "font", "stylesheet"}

                def _block_if_heavy(route) -> None:
                    try:
                        if route.request.resource_type in _BLOCK:
                            route.abort()
                        else:
                            route.continue_()
                    except Exception:
                        try:
                            route.continue_()
                        except Exception:
                            pass

                context.route("**/*", _block_if_heavy)

                page = context.new_page()
                # "commit" returns as soon as headers arrive; we don't need
                # the full DOMContentLoaded, the JS redirect fires before
                # any of the heavy interstitial JS finishes loading.
                page.goto(url, wait_until="commit",
                          timeout=timeout_s * 1000)
                try:
                    page.wait_for_url(
                        lambda u: _looks_like_publisher(u),
                        timeout=timeout_s * 1000,
                    )
                except PWTimeout:
                    pass
                final = page.url
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 — never let resolver crash pipeline
        logger.warning(f"google news resolve failed for {url[:80]}: {e}")
        return None

    if _looks_like_publisher(final):
        return final
    logger.info(
        f"google news resolve ended on non-publisher url: {final[:80]} "
        f"(input: {url[:80]})"
    )
    return None
