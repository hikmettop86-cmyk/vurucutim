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
