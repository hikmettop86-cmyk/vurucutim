from unittest.mock import patch

from short_bot.image_picker import pick_image_for_generator
from short_bot.models import Script


def _script():
    return Script(
        header_top="A", header_bottom="B", photo_overlay="C",
        body_paragraph="x" * 50, highlights=[],
        category="ask", mood="neutral",
    )


def test_pick_image_for_generator_uses_keywords_as_query(tmp_path):
    captured = {}

    def fake_run(query, script, cache_dir, *, claude_path, max_candidates):
        captured["query"] = query
        return None    # simulate no acceptable candidate

    with patch("short_bot.image_picker._run_image_search",
               side_effect=fake_run):
        pick_image_for_generator(
            keywords=["couple silhouette", "sunset"],
            script=_script(), cache_dir=tmp_path,
            claude_path="claude",
        )
    assert captured["query"] == "couple silhouette sunset"


def test_pick_image_for_generator_filters_empty_keywords(tmp_path):
    captured = {}

    def fake_run(query, script, cache_dir, *, claude_path, max_candidates):
        captured["query"] = query
        return None

    with patch("short_bot.image_picker._run_image_search",
               side_effect=fake_run):
        pick_image_for_generator(
            keywords=["couple", "", "sunset"],
            script=_script(), cache_dir=tmp_path,
            claude_path="claude",
        )
    assert captured["query"] == "couple sunset"   # no double space
