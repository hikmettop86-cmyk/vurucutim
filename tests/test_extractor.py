from pathlib import Path
from unittest.mock import patch, MagicMock

from short_bot.extractor import extract_article


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
