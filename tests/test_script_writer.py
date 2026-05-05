from unittest.mock import patch
from datetime import datetime

import pytest

from short_bot.models import NewsItem, Script
from short_bot.script_writer import write_script, build_script_prompt


def _item():
    return NewsItem(guid="g", title="Faiz indirimi", link="http://x", source="Reuters",
                    pub_date=datetime(2026, 5, 5), thumb_url=None,
                    description="Karar şok yarattı.")


def test_build_script_prompt_includes_body_and_title():
    p = build_script_prompt(_item(), "Tam makale gövdesi metni")
    assert "Faiz indirimi" in p
    assert "Tam makale gövdesi metni" in p
    assert "header_top" in p
    assert "highlights" in p


def test_write_script_returns_script_model():
    fake = Script(
        header_top="FAİZ ŞOKU",
        header_bottom="BAŞLADI",
        photo_overlay="250 BAZ PUAN İNDİRİM",
        body_paragraph="Türkiye Cumhuriyet Merkez Bankası faizi 250 baz puan indirdi. Karar piyasada şok yarattı.",
        highlights=[{"text": "250 baz puan", "color": "yellow"}],
        category="EKONOMİ",
        mood="breaking",
    )
    with patch("short_bot.script_writer.run_json", return_value=fake):
        result = write_script(_item(), "Tam makale", claude_path="claude")
    assert isinstance(result, Script)
    assert result.header_top == "FAİZ ŞOKU"
