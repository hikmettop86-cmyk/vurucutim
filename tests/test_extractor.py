from pathlib import Path
from unittest.mock import patch, MagicMock

import requests

from short_bot.extractor import extract_article, extract_og_image_url


def _resp(html: str, status: int = 200):
    r = MagicMock()
    r.status_code = status
    r.text = html
    r.content = html.encode("utf-8")
    return r


def test_extract_article_returns_clean_text():
    html = (Path(__file__).parent / "fixtures" / "article_basic.html").read_text(encoding="utf-8")
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        body = extract_article("http://example.com/x")
    assert body is not None
    assert "Türkiye Cumhuriyet Merkez Bankası" in body
    assert "Site Menü" not in body
    assert "Telif" not in body
    assert len(body) <= 2000


def test_extract_article_returns_none_when_empty():
    html = (Path(__file__).parent / "fixtures" / "article_empty.html").read_text(encoding="utf-8")
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        body = extract_article("http://x")
    assert body is None


def test_extract_article_returns_none_on_http_error():
    with patch("short_bot.extractor.requests.get", return_value=_resp("", status=403)):
        assert extract_article("http://x") is None


def test_extract_article_truncates_to_max_chars():
    big = "<html><body><article>" + ("Uzun bir cümle. " * 1000) + "</article></body></html>"
    with patch("short_bot.extractor.requests.get", return_value=_resp(big)):
        body = extract_article("http://x", max_chars=500)
    assert body is not None and len(body) <= 500


# ---- extract_og_image_url ----

def test_og_image_returns_url_from_og_meta():
    html = """
    <html><head>
        <meta property="og:image" content="https://example.com/hero.jpg">
    </head><body>x</body></html>
    """
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        url = extract_og_image_url("https://example.com/article")
    assert url == "https://example.com/hero.jpg"


def test_og_image_falls_back_to_twitter_image():
    html = """
    <html><head>
        <meta name="twitter:image" content="https://example.com/twitter.jpg">
    </head><body>x</body></html>
    """
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        url = extract_og_image_url("https://example.com/article")
    assert url == "https://example.com/twitter.jpg"


def test_og_image_prefers_og_over_twitter():
    html = """
    <html><head>
        <meta property="og:image" content="https://example.com/og.jpg">
        <meta name="twitter:image" content="https://example.com/twitter.jpg">
    </head><body>x</body></html>
    """
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        url = extract_og_image_url("https://example.com/article")
    assert url == "https://example.com/og.jpg"


def test_og_image_resolves_relative_url():
    html = """
    <html><head>
        <meta property="og:image" content="/images/hero.jpg">
    </head><body>x</body></html>
    """
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        url = extract_og_image_url("https://news.example.com/articles/123")
    assert url == "https://news.example.com/images/hero.jpg"


def test_og_image_resolves_protocol_relative_url():
    html = """
    <html><head>
        <meta property="og:image" content="//cdn.example.com/hero.jpg">
    </head><body>x</body></html>
    """
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        url = extract_og_image_url("https://example.com/article")
    assert url == "https://cdn.example.com/hero.jpg"


def test_og_image_returns_none_when_no_meta():
    html = "<html><head></head><body>just text</body></html>"
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        url = extract_og_image_url("https://example.com/article")
    assert url is None


def test_og_image_returns_none_on_http_error():
    with patch("short_bot.extractor.requests.get", return_value=_resp("", status=404)):
        url = extract_og_image_url("https://example.com/x")
    assert url is None


def test_og_image_returns_none_on_request_exception():
    with patch("short_bot.extractor.requests.get",
               side_effect=requests.RequestException("network")):
        url = extract_og_image_url("https://example.com/x")
    assert url is None


def test_og_image_handles_attribute_order_variation():
    """Meta tag attribute order is publisher-dependent."""
    html = """
    <html><head>
        <meta content="https://example.com/hero.jpg" property="og:image">
    </head><body>x</body></html>
    """
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        url = extract_og_image_url("https://example.com/article")
    assert url == "https://example.com/hero.jpg"


def test_og_image_skips_google_news_intermediate_pages():
    """Google News rss/articles URLs serve a JS-redirect intermediate page;
    requests.get can't follow that, so we'd parse Google's own og:image
    (a generic CDN preview like lh3.googleusercontent.com/...). All GS
    articles return the same preview → identical cached image across
    different stories. Skip the fetch entirely for these hosts."""
    # Even if the fetch would succeed, we should never call it.
    mocked = MagicMock()
    with patch("short_bot.extractor.requests.get") as m:
        m.return_value = _resp(
            '<html><head><meta property="og:image" '
            'content="https://lh3.googleusercontent.com/abc"></head></html>'
        )
        url = extract_og_image_url(
            "https://news.google.com/rss/articles/CBMiabcdef"
        )
        assert url is None
        assert m.call_count == 0, "should not fetch Google News URL"


def test_og_image_skips_news_google_subdomain_too():
    with patch("short_bot.extractor.requests.get") as m:
        url = extract_og_image_url(
            "https://news.google.com/articles/x"
        )
        assert url is None
        assert m.call_count == 0


def test_og_image_still_works_for_direct_publisher_url():
    """Regression guard: only Google News is bypassed; direct publisher
    URLs continue through the og:image extraction path."""
    html = (
        '<html><head><meta property="og:image" '
        'content="https://fanatik.com.tr/hero.jpg"></head></html>'
    )
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        url = extract_og_image_url("https://www.fanatik.com.tr/article")
    assert url == "https://fanatik.com.tr/hero.jpg"
