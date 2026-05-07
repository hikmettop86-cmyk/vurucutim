from unittest.mock import patch
from datetime import datetime

import pytest

from short_bot.models import NewsItem, ScoredItem
from short_bot.scorer import score_items, build_scoring_prompt


def _item(guid, title):
    return NewsItem(guid=guid, title=title, link="http://x", source="S",
                    pub_date=datetime(2026, 5, 5), thumb_url=None, description=None)


def test_build_scoring_prompt_lists_items():
    items = [_item("g1", "A"), _item("g2", "B")]
    prompt = build_scoring_prompt(items)
    assert "g1" in prompt and "g2" in prompt
    assert "A" in prompt and "B" in prompt
    assert "JSON" in prompt or "json" in prompt


def test_score_items_parses_response():
    items = [_item("g1", "Faiz"), _item("g2", "Hava")]
    fake = {
        "scores": [
            {"guid": "g1", "score": 9.2, "reasoning": "kritik"},
            {"guid": "g2", "score": 4.0, "reasoning": "sıkıcı"},
        ]
    }
    with patch("short_bot.scorer.run_json") as m:
        from short_bot.scorer import _ScoreResponse
        m.return_value = _ScoreResponse.model_validate(fake)
        scored = score_items(items, claude_path="claude")
    assert len(scored) == 2
    assert scored[0].score == 9.2 and scored[0].item.guid == "g1"


def test_score_items_skips_unknown_guid():
    items = [_item("g1", "X")]
    fake = {"scores": [{"guid": "g_other", "score": 7, "reasoning": "y"}]}
    with patch("short_bot.scorer.run_json") as m:
        from short_bot.scorer import _ScoreResponse
        m.return_value = _ScoreResponse.model_validate(fake)
        scored = score_items(items, claude_path="claude")
    assert scored == []


def test_score_items_empty_returns_empty():
    assert score_items([], claude_path="claude") == []


def test_score_items_passes_model_to_run_json():
    items = [_item("g1", "X")]
    fake = {"scores": [{"guid": "g1", "score": 7, "reasoning": "y"}]}
    with patch("short_bot.scorer.run_json") as m:
        from short_bot.scorer import _ScoreResponse
        m.return_value = _ScoreResponse.model_validate(fake)
        score_items(items, claude_path="claude", model="haiku")
    # Verify model kwarg propagated to claude CLI
    assert m.call_args.kwargs["model"] == "haiku"


def test_score_items_batches_large_input():
    """75 items + batch_size=30 should produce 3 separate run_json calls."""
    items = [_item(f"g{i}", f"T{i}") for i in range(75)]
    from short_bot.scorer import _ScoreResponse
    # Each batch returns scores for its own items
    def fake_response(prompt, schema, **kw):
        # extract guids from prompt to mimic real LLM behavior
        import re
        guids = re.findall(r"guid=(g\d+)", prompt)
        return _ScoreResponse.model_validate({
            "scores": [{"guid": g, "score": 6.0, "reasoning": ""} for g in guids]
        })
    with patch("short_bot.scorer.run_json", side_effect=fake_response) as m:
        scored = score_items(items, claude_path="claude", batch_size=30)
    assert m.call_count == 3   # 30 + 30 + 15
    assert len(scored) == 75


def test_score_items_continues_when_one_batch_fails():
    """A failing batch must not kill the whole scoring run."""
    items = [_item(f"g{i}", f"T{i}") for i in range(60)]
    from short_bot.scorer import _ScoreResponse
    call_count = {"n": 0}
    def maybe_fail(prompt, schema, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("first batch died")
        import re
        guids = re.findall(r"guid=(g\d+)", prompt)
        return _ScoreResponse.model_validate({
            "scores": [{"guid": g, "score": 5.0, "reasoning": ""} for g in guids]
        })
    with patch("short_bot.scorer.run_json", side_effect=maybe_fail):
        scored = score_items(items, claude_path="claude", batch_size=30)
    # First 30 lost, second 30 scored
    assert len(scored) == 30
