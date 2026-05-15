"""Trend <-> news-headline matching + score boost calculation.

Two match modes, evaluated in order:
1. Whole-word substring (case + diacritic insensitive) -> base_boost
2. rapidfuzz partial_ratio >= fuzzy_threshold -> base_boost * (ratio/100)

Both add a rank bonus when the trend is in top-3 of its source.

Boosts from all matching trends are SUMMED then capped at max_boost. This
lets multi-trend stories (e.g. headline mentions two trending terms) get a
stronger lift than single matches, while the cap prevents one item from
dominating purely on trend overlap.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from short_bot.trends import TrendItem

logger = logging.getLogger(__name__)


_BASE_SUBSTRING_BOOST = 1.0
_BASE_FUZZY_BOOST = 1.5  # multiplied by ratio/100
_TOP_RANK_BONUS = 0.5    # added if trend.rank <= 3
_TOP_RANK_CUTOFF = 3
_FUZZY_MIN_TERM_LENGTH = 6  # below this, fuzzy is too noisy


@dataclass(frozen=True)
class TrendMatch:
    item: TrendItem
    match_type: str       # "substring" | "fuzzy"
    match_score: float    # 0..1 quality (1.0 for substring, ratio/100 for fuzzy)
    boost: float          # per-match boost (uncapped)


def normalize_text(text: str) -> str:
    """Lowercase + strip diacritics + collapse punctuation -> tokenizable form.

    Public so callers/tests can verify the exact normalization rule.
    """
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _whole_word_match(needle: str, haystack: str) -> bool:
    """Match `needle` as a whole-word substring of `haystack`. Both normalized."""
    if not needle or not haystack:
        return False
    pattern = r"\b" + re.escape(needle) + r"\b"
    return bool(re.search(pattern, haystack))


def compute_trend_boost(
    headline: str,
    trends: list[TrendItem],
    *,
    max_boost: float = 2.0,
    min_term_length: int = 4,
    exclude_terms: list[str] | None = None,
    fuzzy_threshold: int = 85,
) -> tuple[float, list[TrendMatch]]:
    """Compute total trend-based boost for a single headline.

    Returns (capped_boost, list_of_matches). Boost is summed across all matches
    then capped at max_boost; matches list is sorted by per-match boost desc.

    Empty trends or no matches -> (0.0, []).
    """
    if not trends or not headline.strip():
        return 0.0, []

    exclude_terms = exclude_terms or []
    exclude_norm = {normalize_text(t) for t in exclude_terms if t.strip()}
    headline_n = normalize_text(headline)

    seen_terms: set[str] = set()  # dedup by normalized term across sources
    matches: list[TrendMatch] = []
    for trend in trends:
        term_n = normalize_text(trend.term)
        if len(term_n) < min_term_length:
            continue
        if term_n in exclude_norm:
            continue
        if term_n in seen_terms:
            continue
        seen_terms.add(term_n)

        # 1. Whole-word substring (cheapest, most precise)
        if _whole_word_match(term_n, headline_n):
            boost = _BASE_SUBSTRING_BOOST
            if trend.rank <= _TOP_RANK_CUTOFF:
                boost += _TOP_RANK_BONUS
            matches.append(TrendMatch(
                item=trend, match_type="substring",
                match_score=1.0, boost=boost,
            ))
            continue

        # 2. Fuzzy partial_ratio (only for longer terms, avoids noise)
        if len(term_n) >= _FUZZY_MIN_TERM_LENGTH:
            ratio = fuzz.partial_ratio(term_n, headline_n)
            if ratio >= fuzzy_threshold:
                quality = ratio / 100.0
                boost = _BASE_FUZZY_BOOST * quality
                if trend.rank <= _TOP_RANK_CUTOFF:
                    boost += _TOP_RANK_BONUS
                matches.append(TrendMatch(
                    item=trend, match_type="fuzzy",
                    match_score=quality, boost=boost,
                ))

    if not matches:
        return 0.0, []

    matches.sort(key=lambda m: m.boost, reverse=True)
    total = sum(m.boost for m in matches)
    return min(total, max_boost), matches
