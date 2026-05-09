"""Tests for dna_cache: save, lookup-by-similarity, cleanup."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select

from short_bot.db import dna_cache, init_db
from short_bot.dna import DnaSpec
from short_bot.dna_cache import (
    CacheHit, cleanup_expired_dna_cache, increment_hit_count,
    lookup_cached_dna, save_cached_dna,
)


@pytest.fixture
def eng(tmp_path):
    db_path = tmp_path / "test.db"
    return init_db(db_path)


def _vec(seed: float) -> list[float]:
    """Construct a 1536-dim test vector dominated by `seed`."""
    return [seed] + [0.0] * 1535


def _sample_dna() -> DnaSpec:
    """Minimal valid DnaSpec for tests."""
    return DnaSpec.model_validate({
        "archetype": "newscast",
        "palette": {
            "primary": "#bb1f1f", "accent": "#ffd54a",
            "bg_gradient": ["#0a0a0a", "#1a1a1a"],
            "body_bg": ["#101010", "#1f1f1f"],
            "text_main": "#ffffff", "text_muted": "#cccccc",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "ciddi", "style": "haber",
            "forbidden": [], "sentence_max_words": 18,
            "paragraph_sentences": [3, 5],
            "body_max_chars": 350, "headline_style_hint": "",
        },
        "persona_summary": "test", "custom_css": "", "ui_badge": "TEST",
    })


def test_save_then_lookup_roundtrip(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "transfer haberi", _vec(1.0), dna, "dynamic-ch1-aaa.css")
    hit = lookup_cached_dna(eng, "ch1", _vec(1.0), threshold=0.85)
    assert hit is not None
    assert hit.archetype == "newscast"
    assert hit.css_filename == "dynamic-ch1-aaa.css"
    assert hit.score > 0.99


def test_lookup_returns_none_below_threshold(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "transfer haberi", _vec(1.0), dna, "x.css")
    other = [0.0] * 1535 + [1.0]
    hit = lookup_cached_dna(eng, "ch1", other, threshold=0.85)
    assert hit is None


def test_lookup_per_channel_isolation(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "x", _vec(1.0), dna, "a.css")
    hit = lookup_cached_dna(eng, "ch2", _vec(1.0), threshold=0.85)
    assert hit is None


def test_lookup_picks_max_cosine(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "near", _vec(0.9), dna, "near.css")
    save_cached_dna(eng, "ch1", "far",  [0.1] + [0.0]*1535, dna, "far.css")
    query = _vec(0.95)
    hit = lookup_cached_dna(eng, "ch1", query, threshold=0.85)
    assert hit is not None
    assert hit.css_filename == "near.css"


def test_increment_hit_count(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "x", _vec(1.0), dna, "x.css")
    hit = lookup_cached_dna(eng, "ch1", _vec(1.0), threshold=0.85)
    assert hit is not None
    increment_hit_count(eng, hit.id)
    increment_hit_count(eng, hit.id)
    with eng.begin() as conn:
        row = conn.execute(select(dna_cache).where(dna_cache.c.id == hit.id)).one()
    assert row.hit_count == 2
    assert row.last_used_at is not None


def test_cleanup_expired_deletes_old_rows_and_files(eng, tmp_path):
    css_dir = tmp_path / "css"; css_dir.mkdir()
    old_css = css_dir / "old.css"; old_css.write_text("/* old */", encoding="utf-8")
    new_css = css_dir / "new.css"; new_css.write_text("/* new */", encoding="utf-8")

    dna = _sample_dna()
    old_dt = datetime.now(timezone.utc) - timedelta(days=120)
    new_dt = datetime.now(timezone.utc) - timedelta(days=10)
    with eng.begin() as conn:
        conn.execute(insert(dna_cache).values(
            channel_slug="ch1", topic_text="old",
            embedding=json.dumps(_vec(1.0)),
            dna_json=dna.model_dump_json(),
            css_filename="old.css", archetype="newscast",
            created_at=old_dt, hit_count=0,
        ))
        conn.execute(insert(dna_cache).values(
            channel_slug="ch1", topic_text="new",
            embedding=json.dumps(_vec(1.0)),
            dna_json=dna.model_dump_json(),
            css_filename="new.css", archetype="newscast",
            created_at=new_dt, hit_count=0,
        ))
    deleted = cleanup_expired_dna_cache(eng, css_dir, days=90)
    assert deleted == 1
    assert not old_css.exists()
    assert new_css.exists()
    with eng.begin() as conn:
        rows = conn.execute(select(dna_cache)).fetchall()
    assert len(rows) == 1
    assert rows[0].topic_text == "new"
