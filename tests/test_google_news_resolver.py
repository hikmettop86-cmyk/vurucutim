"""Unit tests for short_bot.google_news_resolver (no network, no Playwright)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from short_bot.google_news_resolver import (
    is_google_news_url, _looks_like_publisher, resolve,
)


# --- is_google_news_url ----------------------------------------------------

def test_is_google_news_url_matches_news_subdomain():
    assert is_google_news_url("https://news.google.com/rss/articles/CBMi...")


def test_is_google_news_url_rejects_other_google_domains():
    assert not is_google_news_url("https://www.google.com/search?q=x")
    assert not is_google_news_url("https://consent.google.com/")


def test_is_google_news_url_rejects_publisher_urls():
    assert not is_google_news_url("https://www.mynet.com.tr/haber/x")
    assert not is_google_news_url("https://t24.com.tr/gundem/x")


def test_is_google_news_url_handles_empty_or_invalid():
    assert not is_google_news_url("")
    assert not is_google_news_url("not-a-url")


# --- _looks_like_publisher --------------------------------------------------

def test_looks_like_publisher_true_for_external_hosts():
    assert _looks_like_publisher("https://www.mynet.com.tr/haber/x")
    assert _looks_like_publisher("https://www.hurriyet.com.tr/gundem/y")
    assert _looks_like_publisher("https://t24.com.tr/gundem/z")


def test_looks_like_publisher_false_for_google_domains():
    assert not _looks_like_publisher("https://news.google.com/")
    assert not _looks_like_publisher("https://consent.google.com/m?continue=...")
    assert not _looks_like_publisher("https://www.google.com/search?q=x")
    assert not _looks_like_publisher("https://lh3.googleusercontent.com/img.jpg")
    assert not _looks_like_publisher("https://www.youtube.com/watch")


def test_looks_like_publisher_false_for_empty():
    assert not _looks_like_publisher("")
    assert not _looks_like_publisher("not-a-url")


# --- resolve (no-op path) --------------------------------------------------

def test_resolve_returns_input_when_not_gnews():
    """Non-gnews URLs should pass through with NO Playwright invocation."""
    url = "https://www.mynet.com.tr/haber/x"
    with patch("short_bot.google_news_resolver.is_google_news_url",
               return_value=False):
        assert resolve(url) == url


# --- resolve (playwright path) ---------------------------------------------

def _fake_playwright(final_url: str):
    """Build a fake sync_playwright context manager that exposes a Page
    whose .url is final_url after wait_for_url returns."""
    pw_module = MagicMock()
    pw_ctx = MagicMock()
    pw_module.__enter__ = MagicMock(return_value=pw_ctx)
    pw_module.__exit__ = MagicMock(return_value=False)

    page = MagicMock()
    page.url = final_url
    page.goto = MagicMock()
    page.wait_for_url = MagicMock()

    context = MagicMock()
    context.new_page.return_value = page
    context.route = MagicMock()

    browser = MagicMock()
    browser.new_context.return_value = context

    pw_ctx.chromium.launch.return_value = browser
    sync_pw = MagicMock(return_value=pw_module)
    return sync_pw, page, browser


def test_resolve_returns_publisher_url_on_success():
    sync_pw, page, browser = _fake_playwright(
        "https://www.mynet.com.tr/haber/test-haber"
    )
    # Patch the import so it returns our fake module structure
    fake_module = MagicMock()
    fake_module.sync_playwright = sync_pw
    fake_module.TimeoutError = type("PWTimeout", (Exception,), {})
    with patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
        out = resolve("https://news.google.com/rss/articles/CBMi...")
    assert out == "https://www.mynet.com.tr/haber/test-haber"
    browser.close.assert_called_once()


def test_resolve_returns_none_when_final_is_google_domain():
    """If the page never redirected away (still on news.google.com or hit a
    consent.google.com interstitial), return None — caller falls back."""
    sync_pw, page, browser = _fake_playwright(
        "https://consent.google.com/m?continue=..."
    )
    fake_module = MagicMock()
    fake_module.sync_playwright = sync_pw
    fake_module.TimeoutError = type("PWTimeout", (Exception,), {})
    with patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
        out = resolve("https://news.google.com/rss/articles/CBMi...")
    assert out is None


def test_resolve_returns_none_on_playwright_exception():
    """Any exception during Playwright operation must absorb -> None,
    never crash pipeline."""
    fake_module = MagicMock()
    fake_module.sync_playwright = MagicMock(side_effect=RuntimeError("browser dead"))
    fake_module.TimeoutError = type("PWTimeout", (Exception,), {})
    with patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
        out = resolve("https://news.google.com/rss/articles/CBMi...")
    assert out is None


def test_resolve_returns_none_when_playwright_import_fails(monkeypatch):
    """If playwright is not installed at all (edge case), resolve returns
    None gracefully so the pipeline can fall back."""
    # Inject an ImportError when importing playwright.sync_api
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("simulated: playwright not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = resolve("https://news.google.com/rss/articles/CBMi...")
    assert out is None
