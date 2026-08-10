"""Tests for short_bot.topic_taxonomy.normalize_category."""
from __future__ import annotations

from short_bot.topic_taxonomy import normalize_category


def test_case_variants_fold_together():
    """'Transfer' 210, 'transfer' 138 kez yazılmıştı — aynı kovaya girmeli."""
    assert normalize_category("Transfer") == normalize_category("transfer")
    assert normalize_category("TRANSFER") == normalize_category("transfer")


def test_turkish_dotted_capital_i_folds_cleanly():
    """'İ'.lower() Python'da birleşik nokta bırakır ('i̇') — ayrı kova olurdu."""
    assert normalize_category("İLGİNÇ") == normalize_category("ilginç")
    assert "̇" not in normalize_category("İLGİNÇ")


def test_inner_and_outer_whitespace_collapses():
    assert normalize_category("  Futbol   Transfer ") == "futbol transfer"


def test_empty_or_missing_becomes_placeholder():
    assert normalize_category("") == "?"
    assert normalize_category(None) == "?"
    assert normalize_category("   ") == "?"
