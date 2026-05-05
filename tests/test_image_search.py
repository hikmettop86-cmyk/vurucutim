from unittest.mock import patch, MagicMock

from short_bot.image_search import search_images, ImageCandidate


def _ddg_result(image, title="", width=1200, height=800, thumbnail=None):
    return {"image": image, "title": title, "width": width, "height": height,
            "thumbnail": thumbnail}


def test_search_images_returns_candidates():
    fake_results = [
        _ddg_result("https://example.com/a.jpg", title="news photo a"),
        _ddg_result("https://example.com/b.jpg", title="news photo b"),
    ]
    with patch("short_bot.image_search.DDGS") as ddgs_cls:
        instance = MagicMock()
        instance.__enter__.return_value.images.return_value = fake_results
        instance.__exit__.return_value = False
        ddgs_cls.return_value = instance
        candidates = search_images("test query", max_results=2)
    assert len(candidates) == 2
    assert candidates[0].url == "https://example.com/a.jpg"
    assert candidates[0].source_domain == "example.com"


def test_search_images_filters_blocked_domains():
    fake_results = [
        _ddg_result("https://pinterest.com/a.jpg"),
        _ddg_result("https://reuters.com/b.jpg"),
    ]
    with patch("short_bot.image_search.DDGS") as ddgs_cls:
        instance = MagicMock()
        instance.__enter__.return_value.images.return_value = fake_results
        instance.__exit__.return_value = False
        ddgs_cls.return_value = instance
        candidates = search_images("test", max_results=5)
    assert len(candidates) == 1
    assert candidates[0].source_domain == "reuters.com"


def test_search_images_filters_small_width():
    fake_results = [
        _ddg_result("https://example.com/small.jpg", width=400),
        _ddg_result("https://example.com/big.jpg", width=1200),
    ]
    with patch("short_bot.image_search.DDGS") as ddgs_cls:
        instance = MagicMock()
        instance.__enter__.return_value.images.return_value = fake_results
        instance.__exit__.return_value = False
        ddgs_cls.return_value = instance
        candidates = search_images("test", min_width=800)
    assert len(candidates) == 1
    assert candidates[0].url.endswith("big.jpg")


def test_search_images_returns_empty_on_ddg_failure():
    with patch("short_bot.image_search.DDGS", side_effect=RuntimeError("network")):
        candidates = search_images("test")
    assert candidates == []


def test_search_images_retries_on_ratelimit():
    """403 ratelimit on first attempt, then succeeds."""
    fake_results = [_ddg_result("https://example.com/a.jpg")]

    call_count = {"n": 0}

    def fake_ddgs():
        call_count["n"] += 1
        m = MagicMock()
        if call_count["n"] == 1:
            m.__enter__.return_value.images.side_effect = Exception("Ratelimit 403")
        else:
            m.__enter__.return_value.images.return_value = fake_results
        m.__exit__.return_value = False
        return m

    with patch("short_bot.image_search.DDGS", side_effect=fake_ddgs), \
         patch("short_bot.image_search.time.sleep"):  # don't actually wait
        candidates = search_images("test", max_results=2, max_attempts=2)
    assert len(candidates) == 1
    assert call_count["n"] == 2
