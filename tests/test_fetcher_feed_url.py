from pathlib import Path
from unittest.mock import patch

from short_bot.fetcher import fetch_feed_url


def test_fetch_feed_url_parses_fixture():
    fixture = Path(__file__).parent / "fixtures" / "feed_generic.xml"
    raw = fixture.read_bytes()
    with patch("short_bot.fetcher.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = raw
        items = fetch_feed_url("https://ornek.com/rss")
    assert len(items) == 2
    assert items[0].guid == "https://ornek.com/haber/1"
    assert items[0].title == "Icardi'den flaş açıklama"
    assert items[0].link == "https://ornek.com/haber/1"
    assert items[0].thumb_url == "https://ornek.com/img/1.jpg"
    assert items[0].description == "Arjantinli golcü konuştu."
    assert items[1].thumb_url is None


def test_fetch_feed_url_calls_given_url():
    fixture = Path(__file__).parent / "fixtures" / "feed_generic.xml"
    raw = fixture.read_bytes()
    with patch("short_bot.fetcher.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = raw
        fetch_feed_url("https://ornek.com/custom-feed")
    called_url = mock_get.call_args[0][0]
    assert called_url == "https://ornek.com/custom-feed"


def test_fetch_feed_url_returns_empty_on_failure():
    from requests.exceptions import ConnectionError
    with patch("short_bot.fetcher.requests.get", side_effect=ConnectionError()):
        items = fetch_feed_url("https://down.example", max_retries=2, backoff=0)
    assert items == []
