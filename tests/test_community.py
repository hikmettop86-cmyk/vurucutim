"""Tests for short_bot.community — community post draft generation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from short_bot.community import (
    CommunityDraft, build_community_prompt, fetch_recent_short_titles,
    suggest_community_posts, _Drafts,
)
from short_bot.config import ChannelConfig
from short_bot.db import init_db, record_short


def _channel(name="Test Channel", keywords=None, dna=None) -> ChannelConfig:
    return ChannelConfig(
        slug="test", name=name, keywords=keywords or ["test"],
        rss_locale="tr-TR", schedule_cron="0 * * * *", duration_s=6,
        min_score=6.0, max_candidates_per_run=5, template="newscast",
        colors={"primary": "#fff"}, handle="@t", output_dir="out",
        enabled=True, language="tr",
        dna=dna,
    )


# --- fetch_recent_short_titles --------------------------------------------

def test_fetch_recent_returns_titles_newest_first(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    for i, t in enumerate(["A", "B", "C"]):
        record_short(eng, channel="ch", rss_item_guid=f"g{i}", title=t,
                      file_path=f"out/{t}.mp4", duration_s=6,
                      script_json="{}", render_ms=1)
    titles = fetch_recent_short_titles(eng, "ch")
    assert titles == ["C", "B", "A"]


def test_fetch_recent_respects_limit(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    for i in range(10):
        record_short(eng, channel="ch", rss_item_guid=f"g{i}", title=f"T{i}",
                      file_path="o.mp4", duration_s=6, script_json="{}",
                      render_ms=1)
    titles = fetch_recent_short_titles(eng, "ch", limit=3)
    assert len(titles) == 3


def test_fetch_recent_filters_by_channel(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    record_short(eng, channel="a", rss_item_guid="g1", title="A",
                  file_path="o.mp4", duration_s=6, script_json="{}", render_ms=1)
    record_short(eng, channel="b", rss_item_guid="g2", title="B",
                  file_path="o.mp4", duration_s=6, script_json="{}", render_ms=1)
    assert fetch_recent_short_titles(eng, "a") == ["A"]
    assert fetch_recent_short_titles(eng, "b") == ["B"]


def test_fetch_recent_skips_deleted(tmp_path):
    from short_bot.web.extensions import db
    from short_bot.web import create_app
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "x.sqlite"
    eng = init_db(db_path)
    sid = record_short(eng, channel="ch", rss_item_guid="g1", title="Alive",
                        file_path="o.mp4", duration_s=6, script_json="{}",
                        render_ms=1)
    sid2 = record_short(eng, channel="ch", rss_item_guid="g2", title="Dead",
                         file_path="o.mp4", duration_s=6, script_json="{}",
                         render_ms=1)
    # Soft-delete via SQLAlchemy session
    from sqlalchemy import text
    with eng.begin() as conn:
        conn.execute(text("UPDATE shorts SET deleted_at = :ts WHERE id = :id"),
                     {"ts": datetime.now(timezone.utc), "id": sid2})
    titles = fetch_recent_short_titles(eng, "ch")
    assert titles == ["Alive"]


# --- build_community_prompt ------------------------------------------------

def test_prompt_includes_channel_basics():
    p = build_community_prompt(
        _channel(name="Galatasaray", keywords=["galatasaray", "icardi"]),
        recent_titles=["İcardi sözleşme", "Şampiyonluk kutlaması"],
        trend_terms=["mauro icardi", "rams park"],
    )
    assert "Galatasaray" in p
    assert "galatasaray" in p.lower()
    assert "icardi" in p.lower()
    assert "İcardi sözleşme" in p
    assert "mauro icardi" in p


def test_prompt_handles_empty_recent_and_trends():
    p = build_community_prompt(_channel(),
                                 recent_titles=[], trend_terms=[])
    assert "henüz" in p.lower() or "yok" in p.lower()


def test_prompt_includes_format_descriptions():
    p = build_community_prompt(_channel(), recent_titles=[])
    for fmt in ["poll", "question", "nostalgia", "tier_list", "hot_take"]:
        assert fmt in p


def test_prompt_includes_dna_voice_when_dna_set():
    from short_bot.dna import DnaSpec
    raw = {
        "archetype": "stadium",
        "palette": {"primary": "#a90432", "accent": "#fdb913",
                    "bg_gradient": ["#1a0408", "#0a0203"],
                    "body_bg": ["#0f0508", "#19080c"],
                    "text_main": "#ffffff", "text_muted": "#fdb913"},
        "fonts": {"headline": "Oswald", "body": "Inter",
                  "google_imports": ["Oswald", "Inter"]},
        "tone": {"voice": "tutkulu, coşkulu", "style": "vurucu, kısa",
                 "forbidden": ["soğuk akademik dil"],
                 "sentence_max_words": 14, "paragraph_sentences": [2, 4],
                 "body_max_chars": 280, "headline_style_hint": "x"},
        "persona_summary": "Galatasaray taraftarı kanalı",
        "ui_badge": "ASLAN",
    }
    dna = DnaSpec.model_validate(raw)
    p = build_community_prompt(_channel(dna=dna), recent_titles=[])
    assert "tutkulu" in p
    assert "Galatasaray taraftarı" in p


# --- suggest_community_posts -----------------------------------------------

def _drafts_response():
    return _Drafts(drafts=[
        CommunityDraft(format="poll",
                       text="🏆 En güzel an?",
                       options=["🏆 Kupanın kalkması", "🦁 Tezahürat"]),
        CommunityDraft(format="question",
                       text="🦁 Tek kelimeyle Icardi? 💛❤️"),
        CommunityDraft(format="nostalgia",
                       text="👑 Bu maçı hatırlayan?",
                       image_hint="2000 UEFA final golü"),
        CommunityDraft(format="tier_list",
                       text="🦁 En iyi forvet?",
                       options=["1️⃣ Hagi", "2️⃣ Drogba"]),
        CommunityDraft(format="hot_take",
                       text="💥 Net konuşalım — şampiyonlar liginde nereye kadar?"),
    ])


def test_suggest_returns_drafts_list():
    with patch("short_bot.community.run_json", return_value=_drafts_response()):
        out = suggest_community_posts(_channel(), recent_titles=[])
    assert len(out) == 5
    assert {d.format for d in out} == {
        "poll", "question", "nostalgia", "tier_list", "hot_take",
    }


def test_suggest_passes_channel_to_prompt_builder():
    captured = {}
    def fake_run_json(prompt, schema, **kw):
        captured["prompt"] = prompt
        return _drafts_response()
    with patch("short_bot.community.run_json", side_effect=fake_run_json):
        suggest_community_posts(_channel(name="My Channel"), recent_titles=[])
    assert "My Channel" in captured["prompt"]


def test_suggest_propagates_claude_failure():
    from short_bot.claude_cli import ClaudeCliError
    with patch("short_bot.community.run_json",
                side_effect=ClaudeCliError("timeout")):
        with pytest.raises(ClaudeCliError):
            suggest_community_posts(_channel(), recent_titles=[])
