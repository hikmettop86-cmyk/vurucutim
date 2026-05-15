"""Produced-headline dedup layer: catches the case where 3 publishers'
RSS titles diverge but Claude normalizes them all to the same headline."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from short_bot.db import (init_db, mark_processed,
                          fetch_recent_produced_title_embeddings,
                          backfill_produced_embeddings)
from short_bot.dedup import filter_new
from short_bot.models import NewsItem


def _item(guid: str, title: str) -> NewsItem:
    return NewsItem(guid=guid, title=title, link="http://x", source=None,
                    pub_date=None, thumb_url=None, description=None)


# --- mark_processed extended signature -------------------------------------

def test_mark_processed_persists_produced_embedding(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(
        eng, "g1", "RSS title", "ch",
        produced_title_embedding=[0.1, 0.2, 0.3],
    )
    out = fetch_recent_produced_title_embeddings(eng, "ch")
    assert out == [[0.1, 0.2, 0.3]]


def test_mark_processed_legacy_call_leaves_produced_null(tmp_path):
    """Backwards-compat: callers that don't pass produced_title_embedding
    still work; the column stays NULL."""
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "x", "ch")  # no kw args
    assert fetch_recent_produced_title_embeddings(eng, "ch") == []


def test_fetch_recent_produced_lookback_filter(tmp_path):
    """Old rows (outside lookback window) are excluded."""
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "x", "ch", produced_title_embedding=[1, 0, 0])
    # Manually backdate the row 30 days
    from sqlalchemy import text
    from datetime import datetime, timedelta, timezone
    with eng.begin() as conn:
        conn.execute(
            text("UPDATE processed_items SET processed_at = :ts WHERE guid = :g"),
            {"ts": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
             "g": "g1"},
        )
    assert fetch_recent_produced_title_embeddings(eng, "ch", lookback_days=14) == []


# --- New dedup layer in filter_new -----------------------------------------

def _patch_embed(side_effect):
    """Patch embed_text in dedup.py to return canned vectors."""
    return patch("short_bot.dedup.embed_text", side_effect=side_effect)


def test_filter_new_drops_candidate_matching_produced_headline(tmp_path):
    """Stored produced-headline embedding is highly similar to candidate
    RSS-title embedding → candidate dropped via the new layer."""
    eng = init_db(tmp_path / "x.sqlite")
    # Seed: a past short whose Claude-produced header embedding is [1,0,0]
    mark_processed(
        eng, "g_old", "Some old RSS title", "ch",
        produced_title_embedding=[1.0, 0.0, 0.0],
    )
    candidate = _item("g_new", "Different RSS title same topic")
    # Patch embed_text to return [1,0,0] for the candidate too
    with _patch_embed(lambda *a, **kw: [1.0, 0.0, 0.0]):
        out = filter_new(
            eng, [candidate], "ch",
            fuzzy_threshold=0.85,   # fuzzy can't match — different words
            openai_api_key="fake",
        )
    assert out == [], "candidate should have been dropped by produced-headline dedup"


def test_filter_new_keeps_candidate_below_produced_threshold(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(
        eng, "g_old", "Old", "ch",
        produced_title_embedding=[1.0, 0.0, 0.0],
    )
    candidate = _item("g_new", "Totally different topic")
    # Orthogonal embedding (cosine = 0.0)
    with _patch_embed(lambda *a, **kw: [0.0, 1.0, 0.0]):
        out = filter_new(
            eng, [candidate], "ch",
            fuzzy_threshold=0.85,
            openai_api_key="fake",
        )
    assert len(out) == 1
    assert out[0].guid == "g_new"


def test_produced_threshold_param_is_honored(tmp_path):
    """Pass a higher produced_threshold so 0.85 cosine does NOT trigger."""
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(
        eng, "g_old", "Old", "ch",
        produced_title_embedding=[1.0, 0.0, 0.0],
    )
    candidate = _item("g_new", "Same topic")
    # cosine([0.85,0.527,0], [1,0,0]) = 0.85
    with _patch_embed(lambda *a, **kw: [0.85, 0.527, 0.0]):
        out = filter_new(
            eng, [candidate], "ch",
            fuzzy_threshold=0.95,
            openai_api_key="fake",
            produced_threshold=0.95,  # stricter than the candidate's 0.85
            topic_threshold=0.99,     # disable rss-side
        )
    # 0.85 is below 0.95 threshold → kept
    assert len(out) == 1


# --- Backfill --------------------------------------------------------------

def test_backfill_populates_missing_produced_embeddings(tmp_path):
    from short_bot.db import record_short
    eng = init_db(tmp_path / "x.sqlite")
    # Insert a short + its processed_items row (without produced embedding)
    sid = record_short(
        eng, channel="ch", rss_item_guid="g1",
        title="A", file_path="x.mp4", duration_s=6,
        script_json='{"header_top":"SON DAKIKA","header_bottom":"TEST","photo_overlay":"x","body_paragraph":"y","highlights":[],"category":"x","mood":"breaking"}',
        render_ms=1,
    )
    mark_processed(eng, "g1", "A", "ch")   # no produced embedding yet
    # Backfill with patched embed_text
    with patch("short_bot.embeddings.embed_text", return_value=[0.1, 0.2, 0.3]):
        result = backfill_produced_embeddings(eng, "fake-key", days=14)
    assert result["updated"] == 1
    # Verify it landed
    embs = fetch_recent_produced_title_embeddings(eng, "ch")
    assert embs == [[0.1, 0.2, 0.3]]


def test_backfill_idempotent_skips_already_filled(tmp_path):
    from short_bot.db import record_short
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(
        eng, channel="ch", rss_item_guid="g1",
        title="A", file_path="x.mp4", duration_s=6,
        script_json='{"header_top":"X","header_bottom":"Y","photo_overlay":"x","body_paragraph":"y","highlights":[],"category":"x","mood":"breaking"}',
        render_ms=1,
    )
    mark_processed(eng, "g1", "A", "ch",
                   produced_title_embedding=[9.9, 9.9, 9.9])
    with patch("short_bot.embeddings.embed_text", return_value=[0.1, 0.2, 0.3]) as m:
        result = backfill_produced_embeddings(eng, "fake-key", days=14)
        # Already had non-null → not re-fetched
        m.assert_not_called()
    assert result["updated"] == 0


def test_backfill_returns_no_key_marker_when_key_missing(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    result = backfill_produced_embeddings(eng, "", days=14)
    assert result.get("no_key") == 1
    assert result["updated"] == 0
