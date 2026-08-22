from unittest.mock import patch

from short_bot.generator import GeneratorResult, generate_quote
from tests.test_generator_prompt import _channel, _dna


def _fake_result():
    return GeneratorResult(
        text="Aşk, ilk anlayışta başlar.",
        topic_tag="tanisma",
        script={
            "header_top": "AŞK ÜZERİNE",
            "header_bottom": "BUGÜNÜN SÖZÜ",
            "photo_overlay": "Sevgi",
            "body_paragraph": "Aşk, ilk anlayışta başlar. İlk bakış güzelliği, ilk anlayış sevdayı uyandırır.",
            "highlights": [{"text": "ilk anlayışta", "color": "yellow"}],
            "category": "ask",
            "mood": "neutral",
        },
        image_keywords=["couple sunset silhouette", "two hands"],
    )


def test_generate_quote_calls_run_json_with_correct_model():
    with patch("short_bot.generator.run_json", return_value=_fake_result()) as m:
        result = generate_quote(
            channel=_channel(), dna=_dna(),
            forbidden_texts=[], topic_distribution={},
            claude_path="claude", model="sonnet",
        )
    assert result.topic_tag == "tanisma"
    assert m.call_args.kwargs["model"] == "sonnet"
    # GeneratorResult class passed as schema
    assert m.call_args.args[1] is GeneratorResult


def test_generate_quote_passes_forbidden_into_prompt():
    captured = {}

    def fake_run_json(prompt, schema, *, claude_path, model, retries, timeout_s, **_):
        captured["prompt"] = prompt
        return _fake_result()

    with patch("short_bot.generator.run_json", side_effect=fake_run_json):
        generate_quote(channel=_channel(), dna=_dna(),
                       forbidden_texts=["FORBIDDEN-A", "FORBIDDEN-B"],
                       topic_distribution={"x": 5},
                       claude_path="claude", model="sonnet")
    assert "FORBIDDEN-A" in captured["prompt"]
    assert "FORBIDDEN-B" in captured["prompt"]
    assert "x: 5" in captured["prompt"]


def test_generate_quote_forwards_backend_and_api_key():
    with patch("short_bot.generator.run_json", return_value=_fake_result()) as m:
        generate_quote(
            channel=_channel(), dna=_dna(),
            forbidden_texts=[], topic_distribution={},
            claude_path="claude", model="sonnet",
            backend="openrouter", api_key="k",
        )
    assert m.call_args.kwargs["backend"] == "openrouter"
    assert m.call_args.kwargs["api_key"] == "k"
