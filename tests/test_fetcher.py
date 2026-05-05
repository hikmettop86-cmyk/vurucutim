from pathlib import Path
from unittest.mock import patch

from short_bot.fetcher import fetch_rss, build_rss_url


def test_build_rss_url_single_keyword():
    url = build_rss_url(["faiz"], "hl=tr&gl=TR&ceid=TR:tr")
    assert "q=faiz" in url
    assert "hl=tr&gl=TR&ceid=TR:tr" in url


def test_build_rss_url_multi_keyword_or_joined():
    url = build_rss_url(["faiz", "dolar", "deprem"], "hl=tr")
    assert "q=faiz+OR+dolar+OR+deprem" in url


def test_fetch_rss_parses_fixture():
    fixture = Path(__file__).parent / "fixtures" / "rss_son_dakika.xml"
    raw = fixture.read_bytes()
    with patch("short_bot.fetcher.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = raw
        items = fetch_rss(["faiz"], "hl=tr&gl=TR&ceid=TR:tr")
    assert len(items) == 2
    first = items[0]
    assert first.guid == "CBMxxx"
    assert first.source == "Reuters TR"
    assert first.thumb_url == "https://lh3.googleusercontent.com/proxy/abc.jpg"
    assert items[1].thumb_url is None


def test_fetch_rss_retries_on_failure():
    from requests.exceptions import ConnectionError
    with patch("short_bot.fetcher.requests.get",
               side_effect=[ConnectionError(), ConnectionError(),
                            type("R", (), {"status_code": 200, "content": b"<rss version='2.0'><channel></channel></rss>"})()]):
        items = fetch_rss(["x"], "hl=tr", max_retries=3, backoff=0)
    assert items == []


def test_build_rss_url_uses_language_param():
    from short_bot.fetcher import build_rss_url_for_language
    url = build_rss_url_for_language(["x"], "de")
    assert "hl=de" in url
    assert "gl=DE" in url


def test_build_rss_url_for_language_invalid():
    import pytest
    from short_bot.fetcher import build_rss_url_for_language
    with pytest.raises(KeyError):
        build_rss_url_for_language(["x"], "xx")
