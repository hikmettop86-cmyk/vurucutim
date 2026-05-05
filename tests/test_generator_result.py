import pytest
from pydantic import ValidationError

from short_bot.generator import GeneratorResult


def _valid_payload():
    return {
        "text": "Aşk, ilk anlayışta başlar.",
        "topic_tag": "tanisma",
        "script": {
            "header_top": "AŞK ÜZERİNE",
            "header_bottom": "BUGÜNÜN SÖZÜ",
            "photo_overlay": "Sevgi Sözü",
            "body_paragraph": "Aşk, ilk anlayışta başlar. İlk bakışta görünen yalnızca dış güzelliktir; ilk anlayışta uyanan ise asıl sevdadır.",
            "highlights": [{"text": "ilk anlayışta", "color": "yellow"}],
            "category": "ask",
            "mood": "neutral",
        },
        "image_keywords": ["couple sunset silhouette", "two hands holding"],
    }


def test_valid_payload_parses():
    r = GeneratorResult(**_valid_payload())
    assert r.text.startswith("Aşk")
    assert r.topic_tag == "tanisma"
    assert r.script.header_top == "AŞK ÜZERİNE"
    assert len(r.image_keywords) == 2


def test_topic_tag_must_be_lowercase_tr():
    payload = _valid_payload()
    payload["topic_tag"] = "Tanisma"   # uppercase first
    with pytest.raises(ValidationError, match="topic_tag"):
        GeneratorResult(**payload)


def test_topic_tag_must_be_single_word():
    payload = _valid_payload()
    payload["topic_tag"] = "tanisma sabir"   # space
    with pytest.raises(ValidationError, match="topic_tag"):
        GeneratorResult(**payload)


def test_text_length_bounds():
    payload = _valid_payload()
    payload["text"] = "x"   # too short
    with pytest.raises(ValidationError):
        GeneratorResult(**payload)
    payload["text"] = "x" * 250   # too long
    with pytest.raises(ValidationError):
        GeneratorResult(**payload)


def test_image_keywords_count_bounds():
    payload = _valid_payload()
    payload["image_keywords"] = ["only one"]
    with pytest.raises(ValidationError):
        GeneratorResult(**payload)
    payload["image_keywords"] = ["a"] * 9
    with pytest.raises(ValidationError):
        GeneratorResult(**payload)


def test_highlights_must_appear_in_body_paragraph():
    """Inherited from Script validator."""
    payload = _valid_payload()
    payload["script"]["highlights"] = [{"text": "DOES NOT APPEAR", "color": "red"}]
    with pytest.raises(ValidationError, match="paragrafta"):
        GeneratorResult(**payload)
