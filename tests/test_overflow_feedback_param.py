"""Verify write_script forwards overflow_feedback into the prompt."""
from unittest.mock import patch

from short_bot.models import NewsItem
from short_bot.script_writer import write_script


def _item():
    return NewsItem(
        guid="g1", title="Test", link="http://x",
        source=None, pub_date=None, thumb_url=None, description=None,
    )


def test_no_feedback_does_not_change_prompt():
    captured = {}
    def fake_run_json(prompt, *_, **__):
        captured["prompt"] = prompt
        from short_bot.models import Script
        return Script(
            header_top="A", header_bottom="B", photo_overlay="C",
            body_paragraph="D" * 30, category="X", mood="neutral",
            highlights=[],
        )

    with patch("short_bot.script_writer.run_json", side_effect=fake_run_json):
        write_script(_item(), "body html")
    assert "PREVIOUS ATTEMPT" not in captured["prompt"]


def test_feedback_appended_to_prompt():
    captured = {}
    def fake_run_json(prompt, *_, **__):
        captured["prompt"] = prompt
        from short_bot.models import Script
        return Script(
            header_top="A", header_bottom="B", photo_overlay="C",
            body_paragraph="D" * 30, category="X", mood="neutral",
            highlights=[],
        )

    fb = "PREVIOUS ATTEMPT OVERFLOWED ...\n- header_top: 26 -> 14"
    with patch("short_bot.script_writer.run_json", side_effect=fake_run_json):
        write_script(_item(), "body html", overflow_feedback=fb)
    assert "PREVIOUS ATTEMPT" in captured["prompt"]
    assert "header_top: 26 -> 14" in captured["prompt"]
