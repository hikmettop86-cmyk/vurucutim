from unittest.mock import patch, MagicMock

from short_bot.wikimedia_search import search_images_commons


def _api_response(pages):
    """Mock the API JSON shape."""
    return {"query": {"pages": pages}}


def test_search_commons_returns_candidates():
    pages = {
        "1": {
            "title": "File:Reichstag_dome.jpg",
            "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/.../Reichstag_dome_1280.jpg",
                "thumbwidth": 1280, "thumbheight": 853,
                "url": "https://upload.wikimedia.org/.../Reichstag_dome.jpg",
            }],
        },
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _api_response(pages)
    with patch("short_bot.wikimedia_search.requests.get", return_value=resp):
        out = search_images_commons("test", max_results=3)
    assert len(out) == 1
    assert out[0].source_domain.endswith("wikimedia.org")
    assert out[0].width == 1280


def test_search_commons_filters_svg_and_gif():
    pages = {
        "1": {"title": "File:logo.svg", "imageinfo": [{"thumburl": "https://x/logo.svg", "thumbwidth": 1280}]},
        "2": {"title": "File:anim.gif", "imageinfo": [{"thumburl": "https://x/anim.gif", "thumbwidth": 1280}]},
        "3": {"title": "File:photo.jpg", "imageinfo": [{"thumburl": "https://x/photo.jpg", "thumbwidth": 1280, "thumbheight": 800}]},
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _api_response(pages)
    with patch("short_bot.wikimedia_search.requests.get", return_value=resp):
        out = search_images_commons("test")
    assert len(out) == 1
    assert out[0].url.endswith(".jpg")


def test_search_commons_filters_small_width():
    pages = {
        "1": {"title": "File:small.jpg", "imageinfo": [{"thumburl": "https://x/s.jpg", "thumbwidth": 400}]},
        "2": {"title": "File:big.jpg", "imageinfo": [{"thumburl": "https://x/b.jpg", "thumbwidth": 1280, "thumbheight": 720}]},
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _api_response(pages)
    with patch("short_bot.wikimedia_search.requests.get", return_value=resp):
        out = search_images_commons("test", min_width=800)
    assert len(out) == 1
    assert out[0].url.endswith("b.jpg")


def test_search_commons_returns_empty_on_http_error():
    resp = MagicMock()
    resp.status_code = 500
    with patch("short_bot.wikimedia_search.requests.get", return_value=resp):
        out = search_images_commons("test")
    assert out == []
