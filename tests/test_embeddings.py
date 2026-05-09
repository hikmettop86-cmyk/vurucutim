"""Tests for OpenAI embedding HTTP client wrapper."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from short_bot.embeddings import EmbeddingError, embed_text


def _mock_ok_response(vec: list[float]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": [{"embedding": vec}]}
    return resp


def test_embed_text_returns_float_list():
    vec = [0.01] * 1536
    with patch("short_bot.embeddings.requests.post",
               return_value=_mock_ok_response(vec)) as mock_post:
        result = embed_text("hello world", api_key="sk-test")
    assert isinstance(result, list)
    assert len(result) == 1536
    assert result[0] == 0.01
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.openai.com/v1/embeddings"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    body = kwargs["json"]
    assert body["model"] == "text-embedding-3-small"
    assert body["input"] == "hello world"


def test_embed_text_raises_when_no_api_key():
    with pytest.raises(EmbeddingError, match="api_key required"):
        embed_text("hello", api_key="")


def test_embed_text_raises_on_http_error():
    resp = MagicMock()
    resp.status_code = 401
    resp.text = '{"error": "invalid api key"}'
    with patch("short_bot.embeddings.requests.post", return_value=resp):
        with pytest.raises(EmbeddingError, match="HTTP 401"):
            embed_text("hello", api_key="sk-bad")


def test_embed_text_retries_on_5xx_then_succeeds():
    vec = [0.5] * 1536
    err = MagicMock(); err.status_code = 503; err.text = "service down"
    ok = _mock_ok_response(vec)
    with patch("short_bot.embeddings.requests.post",
               side_effect=[err, err, ok]) as mock_post:
        with patch("short_bot.embeddings.time.sleep"):
            result = embed_text("hello", api_key="sk-test")
    assert len(result) == 1536
    assert mock_post.call_count == 3


def test_embed_text_gives_up_after_retries():
    err = MagicMock(); err.status_code = 503; err.text = "down"
    with patch("short_bot.embeddings.requests.post", return_value=err):
        with patch("short_bot.embeddings.time.sleep"):
            with pytest.raises(EmbeddingError, match="HTTP 503"):
                embed_text("hello", api_key="sk-test")


def test_embed_text_validates_dimension():
    """If OpenAI returns wrong-sized vector, raise."""
    short_vec = [0.1] * 100
    with patch("short_bot.embeddings.requests.post",
               return_value=_mock_ok_response(short_vec)):
        with pytest.raises(EmbeddingError, match="unexpected dimension"):
            embed_text("hello", api_key="sk-test")


def test_embed_text_truncates_oversize_input():
    """Input over ~8000 chars should be truncated to OpenAI's token limit."""
    vec = [0.1] * 1536
    huge = "x" * 50000
    with patch("short_bot.embeddings.requests.post",
               return_value=_mock_ok_response(vec)) as mock_post:
        embed_text(huge, api_key="sk-test")
    sent = mock_post.call_args.kwargs["json"]["input"]
    assert len(sent) <= 8000
