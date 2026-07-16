"""Tests for scorer.build_scoring_prompt — includes channel-aware version."""
from __future__ import annotations

from unittest.mock import patch
from datetime import datetime

import pytest

from short_bot.config import ChannelConfig
from short_bot.models import NewsItem, ScoredItem
from short_bot.scorer import score_items, build_scoring_prompt


def _item(guid, title):
    return NewsItem(guid=guid, title=title, link="http://x", source="S",
                    pub_date=datetime(2026, 5, 5), thumb_url=None, description=None)


def _channel(name: str, keywords: list[str], language: str = "tr") -> ChannelConfig:
    return ChannelConfig(
        slug="test", name=name, keywords=keywords, rss_locale=f"{language}-XX",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, language=language,
        max_age_hours=24,
    )


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


# ---------------------------------------------------------------------------
# Channel-aware prompt tests
# ---------------------------------------------------------------------------

def test_prompt_includes_channel_name_and_keywords():
    cfg = _channel("NFL Channel", ["nfl", "american football", "rookie"], language="en")
    items = [_item("1", "WWE Backlash 2026 Results")]
    prompt = build_scoring_prompt(items, channel=cfg)
    assert "NFL Channel" in prompt
    assert "nfl" in prompt or "NFL" in prompt
    assert "american football" in prompt
    assert "rookie" in prompt


def test_prompt_in_english_for_en_channel():
    cfg = _channel("NFL", ["nfl"], language="en")
    items = [_item("1", "Some headline")]
    prompt = build_scoring_prompt(items, channel=cfg)
    # English rubric uses words like "score", "interesting"
    assert "score" in prompt.lower() or "rate" in prompt.lower()


def test_prompt_in_turkish_for_tr_channel():
    cfg = _channel("Spor", ["futbol"], language="tr")
    items = [_item("1", "Trabzonspor Galatasaray maçı")]
    prompt = build_scoring_prompt(items, channel=cfg)
    # Turkish rubric uses words like "puanla", "ilginçlik"
    assert "puanla" in prompt or "Puanla" in prompt or "ilginçlik" in prompt.lower()


def test_prompt_contains_off_topic_penalty_instruction():
    """The prompt must instruct the LLM to penalize off-topic articles."""
    cfg = _channel("NFL", ["nfl"], language="en")
    prompt = build_scoring_prompt([_item("1", "x")], channel=cfg)
    # Look for off-topic / unrelated penalty language
    lower = prompt.lower()
    assert ("off-topic" in lower or "unrelated" in lower
            or "not about" in lower or "off topic" in lower)


def test_prompt_includes_all_item_titles():
    cfg = _channel("X", ["x"], language="en")
    items = [_item("1", "First headline"), _item("2", "Second headline")]
    prompt = build_scoring_prompt(items, channel=cfg)
    assert "First headline" in prompt
    assert "Second headline" in prompt


def test_prompt_emits_correct_json_schema_hint():
    """JSON output schema must remain unchanged so _ScoreResponse parsing works."""
    cfg = _channel("X", ["x"], language="en")
    prompt = build_scoring_prompt([_item("1", "x")], channel=cfg)
    assert '"scores"' in prompt
    assert '"guid"' in prompt
    assert '"score"' in prompt
    assert '"reasoning"' in prompt


def test_score_items_forwards_backend_and_api_key():
    items = [_item("g1", "X")]
    fake = {"scores": [{"guid": "g1", "score": 7, "reasoning": "y"}]}
    with patch("short_bot.scorer.run_json") as m:
        from short_bot.scorer import _ScoreResponse
        m.return_value = _ScoreResponse.model_validate(fake)
        score_items(items, claude_path="claude", model="x",
                    backend="openrouter", api_key="sk-or-k")
    assert m.call_args.kwargs["backend"] == "openrouter"
    assert m.call_args.kwargs["api_key"] == "sk-or-k"


def test_score_items_propagates_openrouter_error():
    from short_bot.claude_cli import OpenRouterError
    items = [_item("g1", "X"), _item("g2", "Y")]
    with patch("short_bot.scorer.run_json", side_effect=OpenRouterError("key yok")):
        with pytest.raises(OpenRouterError):
            score_items(items, claude_path="claude", backend="openrouter", api_key=None)


def test_score_items_raises_on_openrouter_key_missing_real_flow():
    """run_json mock'lanMADAN: key yokken score_items OpenRouterError firlatir (sessiz [] DEGIL)."""
    from short_bot.claude_cli import OpenRouterError
    items = [_item("g1", "X")]
    with patch("short_bot.openrouter_client.complete",
               side_effect=OpenRouterError("key yok")), \
         patch("short_bot.claude_cli.time.sleep"):
        with pytest.raises(OpenRouterError):
            score_items(items, claude_path="claude", backend="openrouter",
                        api_key=None, model="x")
