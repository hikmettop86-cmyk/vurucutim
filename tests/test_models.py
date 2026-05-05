from datetime import datetime
import pytest
from pydantic import ValidationError

from short_bot.models import NewsItem, ScoredItem, Highlight, Script


def test_news_item_minimal():
    item = NewsItem(guid="g1", title="T", link="http://x", source=None, pub_date=None, thumb_url=None, description=None)
    assert item.guid == "g1"


def test_scored_item_score_range():
    item = NewsItem(guid="g", title="t", link="l", source=None, pub_date=None, thumb_url=None, description=None)
    s = ScoredItem(item=item, score=8.5, reasoning="r")
    assert s.score == 8.5


def test_highlight_color_validates():
    Highlight(text="x", color="red")
    Highlight(text="x", color="yellow")
    with pytest.raises(ValidationError):
        Highlight(text="x", color="blue")


def test_script_validation_succeeds():
    s = Script(
        header_top="FAİZ ŞOKU",
        header_bottom="BAŞLADI",
        photo_overlay="250 BAZ PUAN",
        body_paragraph="Türkiye Cumhuriyet Merkez Bankası faizi 250 baz puan indirdi. Karar piyasada şok etkisi yarattı.",
        highlights=[Highlight(text="250 baz puan", color="yellow")],
        category="EKONOMİ",
        mood="breaking",
    )
    assert s.mood == "breaking"


def test_script_highlight_must_be_substring_of_body():
    with pytest.raises(ValidationError, match="paragrafta"):
        Script(
            header_top="A", header_bottom="B", photo_overlay="C",
            body_paragraph="Yeterince uzun bir paragraf metni.",
            highlights=[Highlight(text="bulunmayan ifade", color="red")],
            category="X", mood="neutral",
        )


def test_script_mood_validates():
    with pytest.raises(ValidationError):
        Script(
            header_top="A", header_bottom="B", photo_overlay="C",
            body_paragraph="Yeterince uzun bir paragraf metni.",
            highlights=[],
            category="X", mood="dance-party",
        )
