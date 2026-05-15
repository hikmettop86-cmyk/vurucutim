"""Tests for short_bot.trends.matcher — boost computation."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from short_bot.trends import TrendItem
from short_bot.trends.matcher import (
    compute_trend_boost, normalize_text, _whole_word_match,
)


def _trend(term: str, *, rank: int = 1, source: str = "google_daily",
           region: str = "TR") -> TrendItem:
    return TrendItem(
        term=term, source=source, region=region, rank=rank,
        score=max(0.0, 1.0 - (rank - 1) / 20.0),
        fetched_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
    )


# --- normalize_text ---------------------------------------------------------

def test_normalize_lowercases_and_strips_diacritics():
    assert normalize_text("Galatasaray İcardi") == "galatasaray icardi"
    assert normalize_text("BAYERN MÜNİH") == "bayern munih"
    assert normalize_text("Şampiyonlar Ligi") == "sampiyonlar ligi"


def test_normalize_strips_punctuation_and_collapses_whitespace():
    assert normalize_text("  abc,  def!  ghi.  ") == "abc def ghi"


# --- _whole_word_match ------------------------------------------------------

def test_whole_word_match_hits_exact_word():
    assert _whole_word_match("galatasaray", "galatasaray fenerbahce ozet")


def test_whole_word_match_does_not_match_partial_word():
    assert not _whole_word_match("gala", "galatasaray win")


def test_whole_word_match_empty_returns_false():
    assert not _whole_word_match("", "anything")
    assert not _whole_word_match("term", "")


# --- compute_trend_boost — substring matches --------------------------------

def test_no_trends_returns_zero():
    boost, matches = compute_trend_boost("any headline", [])
    assert boost == 0.0
    assert matches == []


def test_empty_headline_returns_zero():
    trends = [_trend("Galatasaray")]
    boost, matches = compute_trend_boost("", trends)
    assert boost == 0.0


def test_substring_match_gives_base_boost_plus_top_rank_bonus():
    trends = [_trend("Galatasaray", rank=1)]
    boost, matches = compute_trend_boost(
        "Galatasaray Fenerbahce 3-0 SON DAKİKA", trends,
    )
    # base 1.0 + top-3 rank bonus 0.5 = 1.5
    assert boost == 1.5
    assert matches[0].match_type == "substring"
    assert matches[0].item.term == "Galatasaray"


def test_substring_match_without_top_rank_bonus():
    trends = [_trend("Galatasaray", rank=10)]
    boost, _ = compute_trend_boost("Galatasaray Fenerbahce derbisi", trends)
    assert boost == 1.0


def test_diacritic_insensitive_match():
    trends = [_trend("şampiyonlar")]
    boost, matches = compute_trend_boost("Sampiyonlar Ligi finali", trends)
    assert boost > 0
    assert matches[0].match_type == "substring"


def test_case_insensitive_match():
    trends = [_trend("ICARDI", rank=1)]
    boost, _ = compute_trend_boost("icardi istanbul'a indi", trends)
    assert boost > 0


# --- compute_trend_boost — fuzzy --------------------------------------------

def test_fuzzy_match_when_no_substring():
    # Trend "transfer" is a prefix of "transferi" in the headline. The
    # whole-word substring check fails (transfer is not a standalone word in
    # the headline -- only "transferi" is). Fuzzy partial_ratio returns 100
    # because the trend is an exact substring of a haystack word.
    trends = [_trend("transfer", rank=5)]
    boost, matches = compute_trend_boost(
        "Galatasaray icardi transferi gerceklesti", trends,
    )
    assert boost > 0
    assert matches[0].match_type == "fuzzy"


def test_fuzzy_below_threshold_no_match():
    trends = [_trend("completely unrelated topic", rank=5)]
    boost, matches = compute_trend_boost("Galatasaray won today", trends)
    assert boost == 0.0
    assert matches == []


def test_short_term_skips_fuzzy():
    """Terms below FUZZY_MIN_TERM_LENGTH should not even try fuzzy match."""
    trends = [_trend("xyz1", rank=1)]   # 4 chars >= min_term_length but < fuzzy_min(6)
    boost, _ = compute_trend_boost("xyz2 abc def", trends)  # not exact
    assert boost == 0.0


# --- min_term_length filter -------------------------------------------------

def test_terms_shorter_than_min_length_are_skipped():
    trends = [_trend("AI"), _trend("ML", rank=2)]
    boost, _ = compute_trend_boost("AI ML revolution news", trends,
                                    min_term_length=4)
    assert boost == 0.0


def test_custom_min_term_length_lets_short_terms_through():
    trends = [_trend("AI", rank=1)]
    boost, _ = compute_trend_boost("AI revolution today", trends,
                                    min_term_length=2)
    assert boost > 0


# --- exclude_terms ----------------------------------------------------------

def test_exclude_terms_filters_out_unwanted_trend():
    trends = [_trend("hava durumu", rank=1)]
    boost, _ = compute_trend_boost(
        "Istanbul hava durumu yarın yağmurlu", trends,
        exclude_terms=["hava durumu"],
    )
    assert boost == 0.0


def test_exclude_terms_is_diacritic_insensitive():
    trends = [_trend("Şampiyonlar Ligi", rank=1)]
    boost, _ = compute_trend_boost(
        "Şampiyonlar Ligi sonucu", trends,
        exclude_terms=["sampiyonlar ligi"],
    )
    assert boost == 0.0


# --- max_boost cap ----------------------------------------------------------

def test_total_boost_capped_at_max_boost():
    trends = [
        _trend("Galatasaray", rank=1),
        _trend("Icardi", rank=2),
        _trend("transfer", rank=3),
    ]
    # All three substring-match → uncapped would be 4.5; cap at 2.0
    boost, matches = compute_trend_boost(
        "Galatasaray Icardi transfer şoku", trends,
        max_boost=2.0,
    )
    assert boost == 2.0
    assert len(matches) == 3  # all matches still listed


def test_multi_match_sums_below_cap():
    trends = [
        _trend("Galatasaray", rank=10),  # 1.0 (no rank bonus)
        _trend("Icardi", rank=15),       # 1.0
    ]
    # Sum 2.0, cap is 2.5 → uncapped sum returned
    boost, _ = compute_trend_boost(
        "Galatasaray Icardi transfer", trends, max_boost=2.5,
    )
    assert boost == 2.0


# --- dedup across sources ---------------------------------------------------

def test_same_term_from_two_sources_counted_once():
    """If Google Daily AND YouTube both trend 'Galatasaray', only one boost."""
    trends = [
        _trend("Galatasaray", rank=1, source="google_daily"),
        _trend("Galatasaray", rank=1, source="youtube"),
    ]
    boost, matches = compute_trend_boost(
        "Galatasaray Fenerbahce derbisi", trends,
    )
    assert len(matches) == 1   # not 2
    assert boost == 1.5


# --- matches ordering -------------------------------------------------------

def test_matches_sorted_by_boost_descending():
    trends = [
        _trend("Icardi", rank=15),         # boost 1.0
        _trend("Galatasaray", rank=1),     # boost 1.5
    ]
    _, matches = compute_trend_boost(
        "Galatasaray Icardi transfer", trends, max_boost=10,
    )
    assert matches[0].item.term == "Galatasaray"
    assert matches[0].boost > matches[1].boost
