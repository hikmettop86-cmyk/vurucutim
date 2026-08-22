import json
from unittest.mock import patch, MagicMock

import pytest

from short_bot.openrouter_client import complete
from short_bot.claude_cli import OpenRouterError


def _resp(status_code=200, content='{"ok": true}', text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


def test_complete_returns_message_content():
    with patch("short_bot.openrouter_client.requests.post",
               return_value=_resp(content='{"score": 9}')) as p:
        out = complete("prompt", model="anthropic/claude-opus-4.8", api_key="sk-or-x")
    assert out == '{"score": 9}'
    kwargs = p.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer sk-or-x"
    assert kwargs["json"]["model"] == "anthropic/claude-opus-4.8"
    assert kwargs["json"]["response_format"] == {"type": "json_object"}


def test_complete_raises_without_key():
    with pytest.raises(OpenRouterError, match="openrouter_api_key"):
        complete("p", model="x", api_key=None)


def test_complete_retries_without_json_mode_on_400():
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        if "response_format" in kwargs["json"]:
            return _resp(status_code=400, text="json_object unsupported")
        return _resp(content='{"ok": 1}')

    with patch("short_bot.openrouter_client.requests.post", side_effect=fake_post):
        out = complete("p", model="google/gemini-x", api_key="k")
    assert out == '{"ok": 1}'
    assert len(calls) == 2
    assert "response_format" not in calls[1]


def test_complete_raises_on_non_200():
    with patch("short_bot.openrouter_client.requests.post",
               return_value=_resp(status_code=500, text="server error")):
        with pytest.raises(OpenRouterError, match="500"):
            complete("p", model="x", api_key="k")


def test_complete_wraps_network_error():
    import requests
    with patch("short_bot.openrouter_client.requests.post",
               side_effect=requests.ConnectionError("down")):
        with pytest.raises(OpenRouterError, match="ag hatasi|down"):
            complete("p", model="x", api_key="k")


def test_complete_with_image_builds_multimodal_content(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    with patch("short_bot.openrouter_client.requests.post",
               return_value=_resp(content='{"ok": 1}')) as p:
        out = complete("describe", model="google/gemma-4-31b-it",
                       api_key="k", image_path=img)
    assert out == '{"ok": 1}'
    content = p.call_args.kwargs["json"]["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_complete_without_image_stays_text_only():
    with patch("short_bot.openrouter_client.requests.post",
               return_value=_resp(content='{"ok": 1}')) as p:
        complete("hi", model="m", api_key="k")
    assert p.call_args.kwargs["json"]["messages"][0]["content"] == "hi"
